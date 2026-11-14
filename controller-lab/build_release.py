"""Build mod-only installer and source ZIPs from a user-owned game."""
from pathlib import Path
import argparse
import base64
import difflib
import hashlib
import json
import re
import zipfile
from inspect_game import resources
from ui_build import build_ui
from radial_asset import build_ui_assets

LAB=Path(__file__).resolve().parent
ROOT=LAB.parent
EXPECTED_EXE='99ae15860cfdbcdaad0f48e005eee21444046b21de848c1deab9367e8246a3c5'
EXPECTED_LINUX='e615763edb57427e3efded67296c357e2563ee40ebc2aef929e1f180e1b5846e'
DOCS=('README.md','CONTROLS.md','RELEASE-NOTES.md')
INSTALLER=('Common.ps1','Install.ps1','Uninstall.ps1','Install.cmd','Uninstall.cmd',
           'Import-Saves.ps1','Import-Saves.cmd')
SOURCES=('M_PSTPAD.lua','ui_build.py','ui_resources.py','menu_navigation.py','radial_asset.py',
         'inspect_game.py','inspect_linux.py','Build-Plugin.ps1','build_plugin_linux.py','build_release.py',
         'test_controls.py','test_menu_navigation.py','test_distribution.py','test_save_import.py',
         'README.md','PROTOTYPE.md','MENU-CHECKS.md')
NATIVE=('pstcontroller.c','nearby_targets.h','engine_layout.h','controller_loader.c','test_native.c')
NATIVE_LINUX=('pstcontroller_linux.c','nearby_targets.h','engine_layout.h','linux_offsets.h','test_native_linux.c')

def digest(data):
    return hashlib.sha256(data).hexdigest()

def make_patch(original,target):
    """A delta of byte spans; unchanged game UI is never included in a release."""
    left=original.splitlines(keepends=True)
    right=target.splitlines(keepends=True)
    offsets=[0]
    for line in left:
        offsets.append(offsets[-1]+len(line))
    hunks=[]
    for tag,a,b,c,d in difflib.SequenceMatcher(None,left,right,autojunk=False).get_opcodes():
        if tag!='equal':
            hunks.append({'start':offsets[a],'delete':offsets[b]-offsets[a],
                          'insert':base64.b64encode(b''.join(right[c:d])).decode('ascii')})
    return {'format':1,'sourceSha256':digest(original),'targetSha256':digest(target),'hunks':hunks}

def write_zip(path,name,files):
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for relative,data in sorted(files.items()):
            if relative.startswith('/') or '..' in Path(relative).parts:
                raise ValueError('Unsafe package path')
            # Fixed metadata gives repeatable ZIPs for the same inputs.
            info=zipfile.ZipInfo(name+'/'+relative,date_time=(2026,11,13,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o644<<16
            archive.writestr(info,data)

def read_ui(game,binary):
    """Extract the stock UI.menu; both supported builds share it byte-for-byte."""
    if digest((game/binary).read_bytes()) not in (EXPECTED_EXE,EXPECTED_LINUX):
        raise ValueError(f'Unsupported {binary} fingerprint; no release built')
    text=next(data.decode('utf-8-sig').replace('\r\n','\n').replace('\r','\n')
              for name,kind,data in resources(game) if name=='UI' and kind==0x408)
    return text.encode('utf-8')

def version_of():
    return re.search(r"version\s*=\s*'([0-9.]+)'",(LAB/'M_PSTPAD.lua').read_text())[1]

def build_windows(game,out,version):
    original=read_ui(game,'Torment.exe')
    target=build_ui(original.decode()).encode('utf-8')
    patch=make_patch(original,target)
    release={name:(ROOT/'distribution'/name).read_bytes() for name in DOCS+INSTALLER}
    release.update({
        'payload/M_PSTPAD.lua':(LAB/'M_PSTPAD.lua').read_bytes(),
        'payload/pstcontroller.dll':(LAB/'native/pstcontroller.dll').read_bytes(),
        'payload/ControllerLab.exe':(LAB/'native/ControllerLab.exe').read_bytes(),
        'payload/ui-patch.json':json.dumps(patch,separators=(',',':')).encode(),
    })
    release.update({'payload/'+name:data for name,data in build_ui_assets().items()})
    manifest={'version':version,'preview':True,'exeSha256':EXPECTED_EXE,
              'payload':[{'path':name,'sha256':digest(data)} for name,data in sorted(release.items()) if name.startswith('payload/')]}
    release['manifest.json']=json.dumps(manifest,indent=2).encode()
    out.mkdir(parents=True,exist_ok=True)
    name='PSTEE-Xbox-Controller-v'+version
    release_zip=out/(name+'-preview.zip')
    write_zip(release_zip,name,release)
    return release_zip,len(patch['hunks'])

def build_linux(game,out,version):
    original=read_ui(game,'Torment')
    target=build_ui(original.decode()).encode('utf-8')
    patch=make_patch(original,target)
    release={
        'README.md':(ROOT/'distribution'/'linux'/'README.md').read_bytes(),
        'install-deck.sh':(ROOT/'distribution'/'linux'/'install-deck.sh').read_bytes(),
        'uninstall-deck.sh':(ROOT/'distribution'/'linux'/'uninstall-deck.sh').read_bytes(),
        'install.py':(ROOT/'distribution'/'linux'/'install.py').read_bytes(),
        'payload/M_PSTPAD.lua':(LAB/'M_PSTPAD.lua').read_bytes(),
        'payload/libpstcontroller.so':(LAB/'native/libpstcontroller.so').read_bytes(),
        'payload/steam_input_manifest.vdf':(LAB/'steam_input_manifest.vdf').read_bytes(),
        'payload/ui-patch.json':json.dumps(patch,separators=(',',':')).encode(),
    }
    release.update({'payload/'+name:data for name,data in build_ui_assets().items()})
    manifest={'version':version,'preview':True,'exeSha256':EXPECTED_LINUX,
              'payload':[{'path':name,'sha256':digest(data)} for name,data in sorted(release.items()) if name.startswith('payload/')]}
    release['manifest.json']=json.dumps(manifest,indent=2).encode()
    out.mkdir(parents=True,exist_ok=True)
    name='PSTEE-Native-Controller-v'+version
    release_zip=out/(name+'-preview.zip')
    write_zip(release_zip,name,release)
    return release_zip,len(patch['hunks'])

def build_source(game,out,version):
    text=next(data.decode('utf-8-sig').replace('\r\n','\n').replace('\r','\n')
              for name,kind,data in resources(game) if name=='UI' and kind==0x408)
    original=text.encode('utf-8')
    source={name:(ROOT/'distribution'/name).read_bytes() for name in DOCS}
    source['.gitignore']=(ROOT/'distribution/gitignore.template').read_bytes()
    source.update({'controller-lab/'+name:(LAB/name).read_bytes() for name in SOURCES})
    source.update({'controller-lab/native/'+name:(LAB/'native'/name).read_bytes() for name in NATIVE})
    source.update({'controller-lab/native/'+name:(LAB/'native'/name).read_bytes() for name in NATIVE_LINUX if name not in NATIVE})
    source.update({'distribution/'+name:(ROOT/'distribution'/name).read_bytes() for name in DOCS+INSTALLER+('gitignore.template',)})
    source.update({'distribution/linux/'+name:(ROOT/'distribution'/'linux'/name).read_bytes()
                   for name in ('README.md','install.py','test_install.py','install-deck.sh','uninstall-deck.sh')})
    for name in DOCS:
        if version not in source[name].decode('utf-8') and name!='CONTROLS.md':
            raise ValueError('Release documentation version is stale: '+name)
    source_zip=out/(f'PSTEE-Xbox-Controller-v{version}-source.zip')
    write_zip(source_zip,f'PSTEE-Xbox-Controller-v{version}-source',source)
    # Local-only stock fixture for developers; deliberately excluded by whitelist.
    backup=LAB/'backups/UI.menu.original'
    if not backup.exists():
        backup.parent.mkdir(parents=True,exist_ok=True)
        backup.write_bytes(original)
    return source_zip

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-dir',type=Path,required=True)
    parser.add_argument('--out-dir',type=Path,default=ROOT/'dist')
    parser.add_argument('--linux',action='store_true',help='build the native Linux payload; the game dir must hold the Linux Torment binary')
    args=parser.parse_args()
    version=version_of()
    release_zip,hunks=(build_linux if args.linux else build_windows)(args.game_dir,args.out_dir,version)
    source_zip=build_source(args.game_dir,args.out_dir,version)
    print(f'Built {version}: {hunks} UI hunks; no stock UI/game archives bundled')
    sums=''.join(digest(path.read_bytes())+'  '+path.name+'\n' for path in (release_zip,source_zip))
    (args.out_dir/'SHA256SUMS.txt').write_text(sums,encoding='ascii')
    for path in (release_zip,source_zip,args.out_dir/'SHA256SUMS.txt'):
        print(path)
