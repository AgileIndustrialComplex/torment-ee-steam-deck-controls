/* Exercise the actual Linux native interaction implementation against an
 * isolated model owned by this console test. Never opens or reads a game
 * process. Ported from test_native.c; the Windows steering wait/face gates
 * and the SDL_PollEvent filter have no Linux counterpart yet, so their
 * checks are absent, and drop_marked_keys replaces poll_filtered_movie_event.
 */
#undef NDEBUG
#include "pstcontroller_linux.c"
#include <assert.h>

static unsigned test_tick = 1000;
static double results[7];
static int result_count, event_count, warped_x, warped_y;
static unsigned test_ticks(void) { return test_tick; }
static void test_push_number(lua_State *state, double value) { (void)state; results[result_count++] = value; }
static unsigned test_window_id(void *window) { (void)window; return 1; }
static void test_warp(void *window, int x, int y) { (void)window; warped_x = x; warped_y = y; }
static SdlEvent last_event;
static SdlEvent recorded_events[512];
static int test_event(void *event) { memcpy(&last_event, event, sizeof(last_event)); recorded_events[event_count] = last_event; watch_physical_input(NULL, event); ++event_count; return 1; }
static void *expected_world;
static int view_calls;
static int32_t view_target[2];
static void test_set_view(void *world, uint64_t point, int16_t duration) {
    assert(world == expected_world && duration == 0);
    memcpy(view_target, &point, 8);
    ++view_calls;
}
static unsigned test_mouse_state(int *x, int *y) { *x = warped_x; *y = warped_y; return 0; }
static int test_scancode(int key) { return key; }

static int group_clear_count, group_move_count;
static int prepare_run_count, prepared_run, expected_run, expected_append;
static int pending_clear_count;
static int model_factory, path_requests, model_members;
static unsigned char *model_actors[2];
static unsigned char model_nodes[2][32], model_actions[2][128];
static uint16_t test_path_request(void *actor, const int32_t *destination) {
    uint16_t opcode = 0, ticks = 0; int32_t force = 0, queued = 0, point[2];
    memcpy(&opcode, (unsigned char *)actor + 0x3f0, 2);
    memcpy(&ticks, (unsigned char *)actor + 0x3ec, 2);
    memcpy(&force, (unsigned char *)actor + 0x3e8, 4);
    memcpy(&queued, (unsigned char *)actor + 0x348, 4);
    memcpy(point, (unsigned char *)actor + 0x460, 8);
    assert(opcode == 23 && ticks == 77 && force == 0 && queued == 0);
    assert(!memcmp(point, destination, 8));
    ++path_requests; return 1;
}
static void test_clear_pending(void *actor, int preserve) {
    assert(!preserve);
    uint16_t action; memcpy(&action, (unsigned char *)actor + 0x3f0, 2);
    assert(action == 23 || action == 0);
    int32_t empty = 0; memcpy((unsigned char *)actor + 0x348, &empty, 4);
    ++pending_clear_count;
}
static void *expected_area;
static unsigned char *run_game;
static int object_click_count;
static int expected_target_x = 1300, expected_target_y = 1000;
static CRect16 test_container_bounds(void *object) {
    CRect16 rect; memcpy(&rect, (unsigned char *)object + 0x538, 16); return rect;
}
static void test_object_click(void *object, const int32_t *point) {
    (void)object; assert(point[0] == 1060 && point[1] == 1000); ++object_click_count;
}
static void test_clear(void *group) { (void)group; ++group_clear_count; }
static void test_prepare_run(void *area) {
    assert(area == expected_area);
    memcpy(&prepared_run, run_game + 0xb9c0, 4);
    assert(prepared_run == expected_run);
    ++prepare_run_count;
}
static void test_move(void *group, uint64_t point, int append, uint16_t formation, uint64_t origin) {
    (void)group; int32_t position[2]; memcpy(position, &point, 8);
    assert(position[0] == expected_target_x && position[1] == expected_target_y && append == expected_append && formation == 0 && origin == UINT64_MAX);
    assert(controller_steering_active == 1);
    assert(prepared_run == expected_run);
    if (model_factory) {
        for (int index = 0; index < model_members; ++index) {
            unsigned char *actor = model_actors[index];
            void *node = model_nodes[index], *action = model_actions[index];
            int32_t queued = 1, destination[2] = {position[0] - index * 50, position[1] + index * 30};
            uint16_t opcode = 23;
            memcpy(actor + 0x338, &node, 8); memcpy(actor + 0x348, &queued, 4);
            memcpy(model_nodes[index] + 0x10, &action, 8);
            memcpy(model_actions[index], &opcode, 2); memcpy(model_actions[index] + 0x70, destination, 8);
        }
    }
    ++group_move_count;
}

static void put(void *base, size_t offset, const void *value, size_t length) { memcpy((unsigned char *)base + offset, value, length); }
static void ptr(void *base, size_t offset, void *value) { put(base, offset, &value, 8); }
static void integer(void *base, size_t offset, int32_t value) { put(base, offset, &value, 4); }
static void make_actor(unsigned char *actor, void *area, int x, int y, int ea) {
    ptr(actor, 0, engine + 0x1000); actor[8] = 0x31; actor[0x38] = (unsigned char)ea;
    integer(actor, 0xc, x); integer(actor, 0x10, y); ptr(actor, 0x18, area);
    integer(actor, 0x3908, 1); integer(actor, 0x390c, 1);
}
static void row(int slot, int16_t generation, void *object) {
    put(engine, E_OBJECT_ROWS + (size_t)slot * 16, &generation, 2);
    ptr(engine, E_OBJECT_ROWS + (size_t)slot * 16 + 8, object);
}
static void query(int operation, uint32_t id, int focus) {
    result_count = 0; dispatch_nearby(NULL, operation, id, 0, (void *)1, 1024, 768, focus);
    assert(result_count == 7);
}

/* drop_marked_keys model: a scripted poll queue plus a re-push log. */
static SdlEvent poll_queue[16];
static int poll_queue_count, poll_queue_next;
static SdlEvent pushed_events[64];
static int push_log_count;
static int test_poll(void *event) {
    if (poll_queue_next >= poll_queue_count) return 0;
    memcpy(event, &poll_queue[poll_queue_next++], sizeof(SdlEvent));
    return 1;
}
static int test_push(void *event) {
    assert(push_log_count < 64);
    pushed_events[push_log_count++] = *(SdlEvent *)event;
    return 1;
}

int main(void) {
    /* The Linux symbol table places the object rows and globals near
     * 0xf00000, so the synthetic image must span the full 16 MiB. */
    engine = mmap(NULL, 0x1000000, PROT_READ | PROT_WRITE | PROT_EXEC, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    assert(engine && engine != MAP_FAILED);
    engine_image_size = 0x1000000;
    memset(engine, 0, 0x1000000);
    ptr(engine, 0x1080, engine + 0x1200);
    absolute_jump(engine + 0x1200, (void *)test_object_click);
    ptr(engine, 0x1588, engine + 0x1240);
    absolute_jump(engine + 0x1240, (void *)test_container_bounds);

    unsigned char chitin[0x1200] = {0}, game_model[0xc000] = {0}, video[0x400] = {0}, area[0xc00] = {0};
    unsigned char leader[0x5000] = {0}, friend_actor[0x5000] = {0}, hostile[0x5000] = {0}, door[32] = {0}, head[32] = {0};
    ptr(engine, E_CHITIN_PTR, chitin);
    ptr(chitin, CHITIN_GAME, game_model);
    ptr(chitin, CHITIN_VIDEO, video);
    ptr(game_model, 0xa180, area); integer(game_model, 0xa200, 1);
    int16_t one = 1, highest = 3;
    put(game_model, 0xa218, &one, 2); integer(game_model, 0xa2b0, 1);
    ptr(game_model, 0xa2a0, head); integer(head, 0x10, 1); put(engine, E_OBJECT_MAX, &highest, 2);
    integer(video, 0x150, 1024); integer(video, 0x154, 768);
    uint16_t rw = 1024, rh = 768;
    put(engine, E_REF_WIDTH, &rw, 2); put(engine, E_REF_HEIGHT, &rh, 2);
    float zoom = 1; put(area, 0xa14, &zoom, 4); integer(area, 0x698, 800); integer(area, 0x69c, 700);
    make_actor(leader, area, 1000, 1000, 2); make_actor(friend_actor, area, 1060, 1000, 30);
    make_actor(hostile, area, 1030, 1000, 255); door[8] = 0x21; ptr(door, 0x18, area);
    integer(door, 0xc, 1080); integer(door, 0x10, 1000);
    row(0, 1, leader); row(1, 2, friend_actor); row(2, 3, hostile); row(3, 4, door);
    get_ticks = test_ticks; push_number = test_push_number; window_id = test_window_id;
    warp_mouse = test_warp; push_event = test_event; mouse_state = test_mouse_state;

    query(6, 1, 1); assert(results[0] == 1 && results[1] == 0x10002 && results[4] == 0x31);
    assert(results[2] == 260 && results[3] == 300 && results[5] == 60);
    query(6, 2, 1); assert(results[0] == 1 && results[1] == 0x30004 && results[4] == 0x21);
    query(6, 3, 1); assert(results[0] == 0); /* party and hostile excluded */
    query(15, 0x10002, 1); assert(results[0] == 1 && object_click_count == 1 && event_count == 0);
    /* Explicit Talk can activate a companion; automatic proximity/Attack
     * still omit party members, and Talk never targets the speaking leader. */
    int16_t two = 2; put(game_model, 0xa218, &two, 2); integer(game_model, 0xa204, 0x10002);
    result_count = 0; dispatch_nearby(NULL, 6, 1, 3, (void *)1, 1024, 768, 1);
    assert(results[0] == 1 && results[1] == 0x10002 && results[6] == 1);
    result_count = 0; dispatch_nearby(NULL, 15, 0x10002, 3, (void *)1, 1024, 768, 1);
    assert(results[0] == 1 && object_click_count == 2 && event_count == 0);
    result_count = 0; dispatch_nearby(NULL, 6, 1, 1, (void *)1, 1024, 768, 1);
    assert(results[1] == 0x20003 && results[6] == 1);
    query(6, 1, 1); assert(results[1] == 0x30004 && results[6] == 1);
    put(game_model, 0xa218, &one, 2); test_tick += 101;
    query(7, 0x10002, 1); assert(event_count == 1 && warped_x == 260 && warped_y == 284);
    query(8, 0x10002, 1); assert(results[0] == 0 && event_count == 1);
    test_tick += 80; query(8, 0x10002, 1); assert(results[0] == 1 && event_count == 3);
    row(1, 9, friend_actor); query(7, 0x10002, 1); assert(results[0] == 0 && event_count == 3);
    query(7, 0x30004, 0); assert(results[0] == 0 && event_count == 3);
    test_tick += 101; integer(friend_actor, 0x1c98, 0x800); query(6, 1, 1);
    assert(results[1] == 0x30004); /* dead NPC removed */
    integer(door, 0xc, 2000); test_tick += 101; query(6, 1, 1); assert(results[0] == 0);
    result_count = 0; dispatch_nearby(NULL, 6, 1, 1, (void *)1, 1024, 768, 1);
    assert(results[0] == 1 && results[1] == 0x20003); /* attack scan includes hostile actors */
    group_clear_actions = test_clear; group_move = test_move; prepare_group_run = test_prepare_run;
    clear_pending_actions = test_clear_pending;
    expected_area = area; run_game = game_model; expected_run = 0;
    integer(game_model, 0xa2b0, 2);
    unsigned char second_head[32] = {0};
    ptr(head, 0, second_head); integer(second_head, 0x10, 0x10009);
    result_count = 0; dispatch_steering(NULL, 9, 10000, 0, 1, 0);
    assert(results[0] == 300 && group_clear_count == 1 && group_move_count == 1);
    assert(controller_steering_active == 0);
    integer(leader, 0xc, 1280); result_count = 0; dispatch_steering(NULL, 10, 0, 0, 1, 0);
    assert(results[0] == 20 && group_move_count == 1); /* query never restarts route */
    result_count = 0; dispatch_steering(NULL, 11, 1, 0, 0, 0);
    assert(group_clear_count == 2 && !steering_owned); /* focus loss cancels only owned route */
    result_count = 0; dispatch_steering(NULL, 11, 1, 0, 0, 0); assert(group_clear_count == 2);
    expected_run = 1; integer(game_model, 0xb9c0, 1);
    integer(game_model, 0xa2b0, 1); integer(leader, 0xc, 1000); expected_target_x = 1220;
    result_count = 0; dispatch_steering(NULL, 9, 10000, 0, 1, 0); assert(results[0] == 220);
    assert(prepare_run_count == 2 && prepared_run == 1);
    result_count = 0; dispatch_steering(NULL, 11, 0, 0, 1, 0); assert(group_clear_count == 3 && !steering_owned); /* cutscene only relinquishes ownership */
    /* Repeated route renewal must never call the idle/reset path or reapply
     * animation speed. Exercise WALK and RUN with one and two selected actors. */
    integer(friend_actor, 0x1c98, 0);
    for (int members = 1; members <= 2; ++members) {
        integer(game_model, 0xa2b0, members);
        ptr(head, 0, members == 2 ? second_head : NULL);
        for (int running = 0; running <= 1; ++running) {
            expected_run = running; integer(game_model, 0xb9c0, running);
            integer(leader, 0xc, 1000); integer(leader, 0x3f0, 0); integer(leader, 0x348, 0);
            integer(friend_actor, 0x3f0, 23); integer(friend_actor, 0x348, 0);
            expected_target_x = members == 2 ? 1300 : 1220; expected_append = 0;
            result_count = 0; dispatch_steering(NULL, 9, 10000, 0, 1, 0);
            assert(result_count == 2 && results[1] == 1);
            int clears = group_clear_count, prepares = prepare_run_count, moves = group_move_count;
            for (int leg = 0; leg < 12; ++leg) {
                integer(leader, 0xc, 1000 + leg * 100); integer(leader, 0x3f0, 23);
                expected_target_x = 1000 + leg * 100 + (members == 2 ? 300 : 220); expected_append = 1;
                result_count = 0; dispatch_steering(NULL, 9, 10000, 0, 1, 1);
                assert(results[1] == 1 && group_move_count == moves + leg + 1);
                assert(group_clear_count == clears && prepare_run_count == prepares);
                /* Until the engine consumes the future leg, do not add another. */
                integer(leader, 0x348, 1);
                result_count = 0; dispatch_steering(NULL, 9, 10000, 0, 1, 1);
                assert(results[1] == 0 && group_move_count == moves + leg + 1);
                assert(group_clear_count == clears && prepare_run_count == prepares);
                integer(leader, 0x348, 0);
            }
            /* A real turn replaces the route promptly, without reapplying speed. */
            expected_append = 0;
            int pending_clears = pending_clear_count;
            result_count = 0; dispatch_steering(NULL, 9, 10000, 0, 1, 0);
            assert(group_clear_count == clears && prepare_run_count == prepares);
            assert(pending_clear_count == pending_clears + members);
            uint16_t still_moving = 0; memcpy(&still_moving, leader + 0x3f0, 2); assert(still_moving == 23);
            result_count = 0; dispatch_steering(NULL, 11, 1, 0, 1, 0);
            assert(group_clear_count == clears + 1 && !steering_owned);
        }
    }
    /* A new selection with the same leader cannot append to the old group's
     * route; mode change applies speed exactly once before replacement. */
    integer(game_model, 0xa2b0, 2); ptr(head, 0, second_head);
    integer(leader, 0xc, 1000); integer(leader, 0x348, 0); expected_target_x = 1300;
    expected_append = 0; result_count = 0; dispatch_steering(NULL, 9, 10000, 0, 1, 0);
    int changed_clears = group_clear_count, changed_prepares = prepare_run_count;
    integer(game_model, 0xa2b0, 1); ptr(head, 0, NULL); expected_target_x = 1220;
    result_count = 0; dispatch_steering(NULL, 9, 10000, 0, 1, 1);
    assert(group_clear_count == changed_clears + 1 && prepare_run_count == changed_prepares + 1);
    expected_run = 0; integer(game_model, 0xb9c0, 0);
    result_count = 0; dispatch_steering(NULL, 9, 10000, 0, 1, 1);
    assert(group_clear_count == changed_clears + 1 && prepare_run_count == changed_prepares + 2);
    changed_clears = group_clear_count;
    result_count = 0; dispatch_steering(NULL, 11, 0, 0, 1, 0); assert(group_clear_count == changed_clears);
    puts("PASS: 48 WALK/RUN single/group renewals without clear or speed reapply; bounded queue, selection/mode change, turn and release");
    integer(friend_actor, 0x1c98, 0x800);
    /* Regression from the real RUN log: a slower follower still has a queued
     * leg when the leader needs its next leg. The leader must not stop waiting
     * for the follower's queue, and follower moves must remain bounded. */
    integer(game_model, 0xa2b0, 2); ptr(head, 0, second_head);
    integer(leader, 0xc, 1000); integer(leader, 0x348, 0); integer(leader, 0x3f0, 23);
    integer(friend_actor, 0x348, 0); integer(friend_actor, 0x3f0, 23);
    expected_run = 1; integer(game_model, 0xb9c0, 1); expected_append = 0; expected_target_x = 1300;
    result_count = 0; dispatch_steering(NULL, 9, 10000, 0, 1, 0);
    int run_clears = group_clear_count, run_prepares = prepare_run_count, run_moves = group_move_count;
    int follower_replacements = pending_clear_count;
    unsigned char pending_node[32] = {0}, pending_action[128] = {0};
    ptr(friend_actor, 0x338, pending_node); ptr(pending_node, 0x10, pending_action);
    uint16_t movement_opcode = 23; put(pending_action, 0, &movement_opcode, 2);
    for (int leg = 0; leg < 20; ++leg) {
        integer(leader, 0xc, 1000 + leg * 180); integer(leader, 0x3f0, 23); integer(leader, 0x348, 0);
        integer(friend_actor, 0x3f0, 23); integer(friend_actor, 0x348, 1);
        expected_target_x = 1300 + leg * 180; expected_append = 1;
        result_count = 0; dispatch_steering(NULL, 9, 10000, 0, 1, 1);
        assert(results[1] == 1 && group_move_count == run_moves + leg + 1);
        assert(group_clear_count == run_clears && prepare_run_count == run_prepares);
        assert(pending_clear_count == follower_replacements + leg + 1);
        uint16_t leader_action = 0, follower_action = 0;
        memcpy(&leader_action, leader + 0x3f0, 2); memcpy(&follower_action, friend_actor + 0x3f0, 2);
        assert(leader_action == 23 && follower_action == 23);
    }
    /* Pending combat or malformed queues are never discarded as stale moves. */
    uint16_t combat_opcode = 3; put(pending_action, 0, &combat_opcode, 2);
    integer(friend_actor, 0x348, 1); result_count = 0; dispatch_steering(NULL, 9, 10000, 0, 1, 1);
    assert(results[1] == 0 && group_move_count == run_moves + 20 && pending_clear_count == follower_replacements + 20);
    put(pending_action, 0, &movement_opcode, 2); integer(friend_actor, 0x348, 2);
    result_count = 0; dispatch_steering(NULL, 9, 10000, 0, 1, 1); assert(results[1] == 0);
    integer(friend_actor, 0x348, 0); ptr(friend_actor, 0x338, NULL);
    integer(leader, 0xc, 1000); integer(game_model, 0xa2b0, 1); ptr(head, 0, NULL);
    result_count = 0; dispatch_steering(NULL, 11, 0, 0, 1, 0);
    puts("PASS: 20 RUN renewals with a lagging queued follower; no idle/reset or speed reapply; unrelated queues preserved");
    /* RUN keeps the same active action instead of ending/starting another
     * waypoint. Execute actual destination-update code against this owned
     * model, with stock group destination generation and path requests mocked. */
    model_factory = 1; request_move_path = test_path_request;
    model_actors[0] = leader; model_actors[1] = friend_actor;
    int16_t area_width = 16000, area_height = 16000;
    put(area, 0x688, &area_width, 2); put(area, 0x68c, &area_height, 2);
    ptr(leader, 0, engine + E_VTABLE_SPRITE); ptr(friend_actor, 0, engine + E_VTABLE_SPRITE);
    for (int members = 1; members <= 2; ++members) {
        model_members = members; integer(game_model, 0xa2b0, members);
        ptr(head, 0, members == 2 ? second_head : NULL);
        expected_run = 1; integer(game_model, 0xb9c0, 1); integer(leader, 0xc, 1000);
        expected_append = 0; expected_target_x = members == 1 ? 1220 : 1300;
        result_count = 0; dispatch_steering(NULL, 9, 10000, 0, 1, 0);
        int before_paths = path_requests, before_prepares = prepare_run_count, before_clears = group_clear_count;
        for (int index = 0; index < members; ++index) {
            integer(model_actors[index], 0x3f0, 23); integer(model_actors[index], 0x3ec, 77);
            integer(model_actors[index], 0x3e8, 0); integer(model_actors[index], 0x348, 0);
        }
        for (int leg = 0; leg < 40; ++leg) {
            integer(leader, 0xc, 1000 + leg * 100); expected_target_x = 1000 + leg * 100 + (members == 1 ? 220 : 300);
            expected_append = 1;
            result_count = 0; dispatch_steering(NULL, 9, 10000, 0, 1, leg % 5 != 0); /* include turns/recovery */
            assert(results[1] == 1 && path_requests == before_paths + (leg + 1) * members);
            assert(group_clear_count == before_clears && prepare_run_count == before_prepares);
            for (int index = 0; index < members; ++index) {
                int32_t point[2], queued = 0; uint16_t opcode = 0, ticks = 0;
                memcpy(point, model_actors[index] + 0x460, 8); memcpy(&queued, model_actors[index] + 0x348, 4);
                memcpy(&opcode, model_actors[index] + 0x3f0, 2); memcpy(&ticks, model_actors[index] + 0x3ec, 2);
                assert(point[0] == expected_target_x - index * 50 && point[1] == 1000 + index * 30);
                assert(queued == 0 && opcode == 23 && ticks == 77); /* no new action, no reset elapsed ticks */
            }
        }
        result_count = 0; dispatch_steering(NULL, 11, 0, 0, 1, 0);
    }
    /* WALK turns retain the same live action as RUN; straight extensions still
     * queue normally. Include an obsolete future move and real direction
     * changes with formation offsets, preserved action/ticks and force flag. */
    for (int members = 1; members <= 2; ++members) {
        model_members = members; integer(game_model, 0xa2b0, members);
        ptr(head, 0, members == 2 ? second_head : NULL);
        expected_run = 0; integer(game_model, 0xb9c0, 0); integer(leader, 0xc, 1000);
        expected_append = 0; expected_target_x = members == 1 ? 1220 : 1300;
        result_count = 0; dispatch_steering(NULL, 9, 10000, 0, 1, 0);
        int paths_before = path_requests, clears_before = group_clear_count, prepares_before = prepare_run_count;
        for (int index = 0; index < members; ++index) {
            integer(model_actors[index], 0x3f0, 23); integer(model_actors[index], 0x3ec, 77);
            integer(model_actors[index], 0x3e8, 0);
        }
        for (int turn = 0; turn < 24; ++turn) {
            int dy = (turn % 3 - 1) * 2000, lookahead = members == 1 ? 220 : 300;
            double length = sqrt(10000.0 * 10000 + (double)dy * dy);
            expected_target_x = 1000 + (int32_t)(10000 / length * lookahead);
            expected_target_y = 1000 + (int32_t)(dy / length * (lookahead * 0.75)); expected_append = 1;
            result_count = 0; dispatch_steering(NULL, 9, 10000, dy, 1, 0);
            assert(results[1] == 1 && path_requests == paths_before + (turn + 1) * members);
            assert(group_clear_count == clears_before && prepare_run_count == prepares_before);
            for (int index = 0; index < members; ++index) {
                int32_t point[2], queued = 0; uint16_t opcode = 0, ticks = 0;
                memcpy(point, model_actors[index] + 0x460, 8); memcpy(&queued, model_actors[index] + 0x348, 4);
                memcpy(&opcode, model_actors[index] + 0x3f0, 2); memcpy(&ticks, model_actors[index] + 0x3ec, 2);
                assert(point[0] == expected_target_x - index * 50 && point[1] == expected_target_y + index * 30);
                assert(queued == 0 && opcode == 23 && ticks == 77);
            }
        }
        expected_target_y = 1000;
        result_count = 0; dispatch_steering(NULL, 11, 0, 0, 1, 0);
    }
    /* A wrong class or invalid destination cannot trigger a memory update. */
    model_members = 1; integer(game_model, 0xa2b0, 1); ptr(head, 0, NULL);
    expected_run = 0; integer(game_model, 0xb9c0, 0); integer(leader, 0xc, 1000);
    expected_append = 0; expected_target_x = 1220;
    result_count = 0; dispatch_steering(NULL, 9, 10000, 0, 1, 0);
    integer(leader, 0x3f0, 23); integer(leader, 0x3ec, 77); integer(leader, 0x348, 0);
    int before_walk_paths = path_requests;
    expected_append = 1; result_count = 0; dispatch_steering(NULL, 9, 10000, 0, 1, 1);
    int32_t walk_future = 0; memcpy(&walk_future, leader + 0x348, 4);
    assert(results[1] == 1 && walk_future == 1 && path_requests == before_walk_paths);
    result_count = 0; dispatch_steering(NULL, 11, 0, 0, 1, 0);
    int32_t rejected_destination[2], old_destination[2]; memcpy(old_destination, leader + 0x460, 8);
    integer(leader, 0x348, 1); ptr(leader, 0x338, model_nodes[0]);
    ptr(leader, 0, engine + 0x1000); assert(!retarget_active_move((uintptr_t)leader, (uintptr_t)area, rejected_destination));
    ptr(leader, 0, engine + E_VTABLE_SPRITE); int32_t outside[2] = {20000, 1000}; put(model_actions[0], 0x70, outside, 8);
    assert(!retarget_active_move((uintptr_t)leader, (uintptr_t)area, rejected_destination));
    assert(!memcmp(old_destination, leader + 0x460, 8));
    request_move_path = NULL; model_factory = 0; integer(leader, 0x348, 0);
    ptr(leader, 0, engine + 0x1000); ptr(friend_actor, 0, engine + 0x1000);
    integer(leader, 0xc, 1000); integer(game_model, 0xa2b0, 1); ptr(head, 0, NULL);
    puts("PASS: 80 RUN retargets and 48 WALK turns, solo/group; current action/ticks/formation preserved; WALK straight queue unchanged; invalid writes refused");
    /* Region subtype filtering and exact container rectangles. */
    unsigned char container[0xa00] = {0}, region[0x600] = {0};
    container[8] = 0x11; ptr(container, 0, engine + 0x1400); ptr(container, 0x18, area);
    integer(container, 0x538, 1060); integer(container, 0x53c, 990); integer(container, 0x540, 1100); integer(container, 0x544, 1010);
    region[8] = 0x41; ptr(region, 0x18, area); integer(region, 0x53c, 1040); integer(region, 0x540, 990);
    integer(region, 0x544, 1060); integer(region, 0x548, 1010); integer(region, 0x57c, 123);
    row(4, 5, container); row(5, 6, region); highest = 5; put(engine, E_OBJECT_MAX, &highest, 2);
    test_tick += 101; query(6, 1, 1); assert(results[1] == 0x40005 && results[4] == 0x11);
    uint16_t info = 1; put(region, 0x538, &info, 2); test_tick += 101; query(6, 1, 1); assert(results[1] == 0x50006);
    integer(region, 0x57c, -1); test_tick += 101; query(6, 1, 1); assert(results[1] == 0x40005);
    uint16_t ground = 4; put(container, 0x590, &ground, 2); test_tick += 101; query(6, 1, 1); assert(results[0] == 0);
    integer(container, 0x570, 2); test_tick += 101; query(6, 1, 1); assert(results[1] == 0x40005);
    /* Area/generation failures never dereference invalid pointers. */
    ptr(game_model, 0xa180, NULL); query(6, 1, 1); assert(results[0] == 0);
    /* Zoom uses a world motion anchor followed by one stock wheel event. */
    int before_zoom = event_count;
    assert(queue_world_zoom((void *)1, 1, 1024, 768, 1));
    assert(event_count == before_zoom + 2 && warped_x == 512 && warped_y == 288);
    assert(last_event.wheel.type == 0x403 && last_event.wheel.window == 1);
    assert(last_event.wheel.y == 1 && last_event.wheel.direction == 0 && last_event.wheel.precise_y == 1);
    assert(queue_world_zoom((void *)1, -1, 1024, 768, 1));
    assert(last_event.wheel.y == -1 && last_event.wheel.precise_y == -1);
    before_zoom = event_count;
    assert(!queue_world_zoom((void *)1, 1, 1024, 768, 0));
    assert(!queue_world_zoom((void *)1, 5, 1024, 768, 1));
    assert(!queue_world_zoom(NULL, 1, 1024, 768, 1));
    assert(event_count == before_zoom);
    /* Real click recognition never consumes stock events or counts our own
     * SDL clicks/warps/wheel/key events as switching back to PC controls. */
    long before_click = physical_click_serial;
    mouse_click((void *)1, 200, 300, 1); assert(physical_click_serial == before_click);
    int before_double = event_count;
    mouse_double_click((void *)1, 500, 537);
    assert(event_count == before_double + 5 && physical_click_serial == before_click);
    assert(recorded_events[before_double].motion.type == 0x400);
    for (int i = 1; i <= 4; ++i) {
        SdlEvent *click = &recorded_events[before_double + i];
        assert(click->mouse.type == (i % 2 ? 0x401u : 0x402u));
        assert(click->mouse.button == 1 && click->mouse.x == 500 && click->mouse.y == 537);
        assert(click->mouse.which == CONTROLLER_MOUSE_ID);
    }
    /* Pan calls the examined stock view setter, with zoom/viewport conversion,
     * without cursor warps, button input, actor writes or a lingering pan state. */
    expected_world = game_model; set_world_view = test_set_view;
    ptr(chitin, CHITIN_WORLD_SCREEN, expected_world); ptr(chitin, CHITIN_ACTIVE_ENGINE, expected_world);
    ptr(game_model, 0xa180, area); integer(area, 0x698, 100); integer(area, 0x69c, 200);
    integer(video, 0x150, 1024); integer(video, 0x154, 768);
    uint16_t pan_rw = 1024, pan_rh = 768; float pan_zoom = 1;
    put(engine, E_REF_WIDTH, &pan_rw, 2); put(engine, E_REF_HEIGHT, &pan_rh, 2); put(area, 0xa14, &pan_zoom, 4);
    int before_pan = event_count;
    assert(pan_world_camera(20, -30, 1024, 768, 1)); assert(view_calls == 1 && view_target[0] == 120 && view_target[1] == 170);
    pan_zoom = 2; put(area, 0xa14, &pan_zoom, 4);
    assert(pan_world_camera(-20, 30, 1024, 768, 1)); assert(view_target[0] == 60 && view_target[1] == 260);
    assert(!pan_world_camera(20, 30, 1024, 768, 0));
    assert(!pan_world_camera(129, 30, 1024, 768, 1));
    ptr(chitin, CHITIN_ACTIVE_ENGINE, video); assert(!pan_world_camera(20, 30, 1024, 768, 1));
    ptr(chitin, CHITIN_ACTIVE_ENGINE, expected_world); ptr(game_model, 0xa180, NULL);
    assert(!pan_world_camera(20, 30, 1024, 768, 1));
    assert(view_calls == 2 && event_count == before_pan);
    /* Follow is actor-ID based, not a boolean toggle. Release the owned ID
     * after selection changes; manual pan/PC edge intent overrides stale locks. */
    ptr(game_model, 0xa180, area); integer(head, 0x10, 1); integer(game_model, 0xa2b0, 1);
    integer(game_model, 0xa58, -1);
    follow_owned = 0; assert(controller_camera_follow(1, 1) && follow_owned && follow_owner_id == 1);
    integer(head, 0x10, 0x10009);
    assert(controller_camera_follow(0, 1) && !follow_owned);
    int32_t follow_value = 0; memcpy(&follow_value, game_model + 0xa58, 4); assert(follow_value == -1);
    integer(head, 0x10, 1); assert(controller_camera_follow(1, 1));
    integer(game_model, 0xa58, 99); assert(!controller_camera_follow(0, 1));
    memcpy(&follow_value, game_model + 0xa58, 4); assert(follow_value == 99); /* preserve a newer user follow lock */
    assert(controller_camera_follow(2, 1)); memcpy(&follow_value, game_model + 0xa58, 4); assert(follow_value == -1);
    assert(!controller_camera_follow(1, 0)); integer(game_model, 0xa58, 123);
    assert(!controller_camera_follow(2, 0));
    ptr(chitin, CHITIN_ACTIVE_ENGINE, video); assert(!controller_camera_follow(2, 1));
    memcpy(&follow_value, game_model + 0xa58, 4); assert(follow_value == 123);
    ptr(chitin, CHITIN_ACTIVE_ENGINE, expected_world); assert(controller_camera_follow(2, 1));
    assert(controller_camera_follow(1, 1)); ptr(chitin, CHITIN_ACTIVE_ENGINE, video);
    assert(controller_camera_follow(0, 1)); /* menu switch still releases owned follow */
    ptr(chitin, CHITIN_ACTIVE_ENGINE, expected_world);
    puts("PASS: camera actor-ID follow release after selection/menu change; manual pan/PC edge unlock; user follow ownership and focus guards");
    SdlEvent real_click = {0}; real_click.mouse.type = 0x401; real_click.mouse.which = 0;
    real_click.mouse.button = 1; assert(watch_physical_input(NULL, &real_click) == 1);
    assert(physical_click_serial == before_click + 1);
    real_click.mouse.type = 0x402; watch_physical_input(NULL, &real_click); assert(physical_click_serial == before_click + 1);
    real_click.mouse.type = 0x401; real_click.mouse.button = 3; watch_physical_input(NULL, &real_click);
    assert(physical_click_serial == before_click + 2);
    real_click.mouse.which = CONTROLLER_MOUSE_ID; watch_physical_input(NULL, &real_click);
    assert(physical_click_serial == before_click + 2);
    /* Startup movie input is limited to the active movie engine/player. */
    unsigned char movie_model[0x100] = {0};
    ptr(chitin, CHITIN_MOVIE_PROJECTOR, movie_model); ptr(chitin, CHITIN_ACTIVE_ENGINE, movie_model);
    assert(!movie_playing()); ptr(movie_model, 0x58, area); assert(movie_playing());
    ptr(chitin, CHITIN_ACTIVE_ENGINE, game_model); assert(!movie_playing());
    movie_a_previous = 0;
    assert(!movie_skip_edge(1, 1, 0, XINPUT_GAMEPAD_A));
    assert(!movie_skip_edge(1, 1, 1, XINPUT_GAMEPAD_A)); /* held across transition */
    assert(!movie_skip_edge(1, 1, 1, 0));
    assert(movie_skip_edge(1, 1, 1, XINPUT_GAMEPAD_A));
    assert(!movie_skip_edge(1, 1, 1, XINPUT_GAMEPAD_A));
    assert(!movie_skip_edge(1, 0, 1, 0));
    assert(!movie_skip_edge(1, 0, 1, XINPUT_GAMEPAD_A));
    assert(!movie_skip_edge(1, 1, 1, XINPUT_GAMEPAD_A)); /* focus regain while held */
    assert(!movie_skip_edge(0, 1, 1, 0));
    get_scancode = test_scancode; before_zoom = event_count;
    keyboard_event_marked((void *)1, 27, 1, CONTROLLER_MOVIE_KEY_ID);
    assert(last_event.key.type == 0x300 && last_event.key.key == 27 && last_event.key.unused == CONTROLLER_MOVIE_KEY_ID);
    keyboard_event_marked((void *)1, 27, 0, CONTROLLER_MOVIE_KEY_ID);
    assert(event_count == before_zoom + 2 && last_event.key.type == 0x301);
    assert(marked_keys_queued);
    sdl_poll_event_fn = (PollEventFn)test_poll;
    sdl_push_event_fn = (PushEventFn)test_push;
    /* While the movie is playing, marked keys stay in the queue untouched. */
    ptr(chitin, CHITIN_ACTIVE_ENGINE, movie_model);
    memset(poll_queue, 0, sizeof(poll_queue)); push_log_count = 0; poll_queue_count = 3; poll_queue_next = 0;
    poll_queue[0] = last_event;                                   /* marked keydown */
    poll_queue[1].key.type = 0x300; poll_queue[1].key.key = 13;   /* stock keydown */
    poll_queue[2] = recorded_events[before_double];               /* stock motion */
    drop_marked_keys();
    assert(poll_queue_next == 0 && push_log_count == 0 && marked_keys_queued);
    /* Once playback ended, a leftover marked Escape never reaches the engine,
     * and replayed stock input is not recounted as a physical click. */
    ptr(chitin, CHITIN_ACTIVE_ENGINE, game_model);
    long before_drop_click = physical_click_serial;
    poll_queue[3].mouse.type = 0x401; poll_queue[3].mouse.which = 0; poll_queue[3].mouse.button = 1;
    poll_queue_count = 4;
    drop_marked_keys();
    assert(poll_queue_next == 4 && push_log_count == 3 && !marked_keys_queued);
    assert(pushed_events[0].key.key == 13 && pushed_events[1].motion.type == 0x400 && pushed_events[2].mouse.type == 0x401);
    assert(physical_click_serial == before_drop_click);
    puts("PASS: native interactions/geometry/focus; movie engine guard, fresh A edge, marked skip dropped after playback and no Escape leak into menus");
    munmap(engine, 0x1000000);
    return 0;
}
