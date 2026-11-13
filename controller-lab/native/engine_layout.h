/* Engine-layout constants shared by the Windows and Linux bridges.
 *
 * The Windows x64 3.2.2.0 build (pstcontroller.c) and the Linux build
 * (pstcontroller_linux.c) execute the same engine code, so CGameArea /
 * CGameSprite / CInfGame member offsets are identical. Two things differ:
 * the addresses of engine globals/vtables inside the image, and five
 * CBaldurChitin member slots. Both builds therefore express every
 * build-specific constant through the E_* / CHITIN_* names below.
 */
#ifndef ENGINE_LAYOUT_H
#define ENGINE_LAYOUT_H

#ifdef PSTPAD_LINUX

#include "linux_offsets.h"

#define E_CHITIN_PTR     LX_G_PBALDURCHITIN_ADDR
#define E_OBJECT_ROWS    LX_OBJECT_ROWS_ADDR
#define E_OBJECT_MAX     LX_OBJECT_MAX_INDEX_ADDR
#define E_REF_WIDTH      LX_REFERENCE_WIDTH_ADDR
#define E_REF_HEIGHT     LX_REFERENCE_HEIGHT_ADDR
#define E_VTABLE_SPRITE  LX_VTABLE_CGAMESPRITE_ADDR
#define E_SLOT_SELECTED  LX_SLOT_SELECTED_GETTER
#define E_SLOT_CLICK     LX_SLOT_OBJECT_CLICK
#define E_SLOT_BOUNDS    LX_SLOT_CONTAINER_BOUNDS

#else /* Windows x64 3.2.2.0, SHA-256 99ae1586...46a3c5 */

#define E_CHITIN_PTR     0x72c278u
#define E_OBJECT_ROWS    0x72d860u
#define E_OBJECT_MAX     0x72d854u
#define E_REF_WIDTH      0x72120cu
#define E_REF_HEIGHT     0x721210u
#define E_VTABLE_SPRITE  0x649328u
#define E_SLOT_SELECTED  0x1c0u
#define E_SLOT_CLICK     0x78u
#define E_SLOT_BOUNDS    0x180u

#define CHITIN_GAME            0x10c8u
#define CHITIN_ACTIVE_ENGINE   0x260u
#define CHITIN_VIDEO           0x268u
#define CHITIN_MOVIE_PROJECTOR 0x10d8u
#define CHITIN_WORLD_SCREEN    0x1148u

#endif

/* The movie player pointer inside CBaldurProjector (same on both builds). */
#define E_MOVIE_PLAYER 0x58u

#endif
