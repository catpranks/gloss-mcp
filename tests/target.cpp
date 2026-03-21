#include <cstdint>
#include <cstdio>
#include <cstring>

// --- Vec3 ---

struct Vec3 {
    float x, y, z;

    Vec3 operator+(const Vec3& o) const { return {x + o.x, y + o.y, z + o.z}; }
    Vec3 operator-(const Vec3& o) const { return {x - o.x, y - o.y, z - o.z}; }
    float dot(const Vec3& o) const { return x * o.x + y * o.y + z * o.z; }
    float length_sq() const { return dot(*this); }
};

// --- Flags bitfield ---

struct EntityFlags {
    uint32_t alive       : 1;
    uint32_t visible     : 1;
    uint32_t invulnerable: 1;
    uint32_t on_ground   : 1;
    uint32_t crouching   : 1;
    uint32_t scoped      : 1;
    uint32_t _pad        : 26;
};

// --- Enums ---

enum class EntityType : uint8_t {
    Unknown = 0,
    Player,
    NPC,
    Projectile,
    Pickup,
    Trigger,
};

enum class WeaponId : uint32_t {
    Fists = 0,
    Pistol,
    Shotgun,
    Rifle,
    Sniper,
    Rocket,
    COUNT
};

// --- Packed network struct ---

#pragma pack(push, 1)
struct NetEntityState {
    uint32_t entity_id;
    uint8_t  type;
    uint8_t  team;
    uint16_t health;
    float    pos[3];
    float    yaw;
    float    pitch;
    uint8_t  flags;
    uint32_t weapon;
};
#pragma pack(pop)

// --- Inventory ---

struct InventorySlot {
    WeaponId weapon;
    uint16_t ammo;
    uint16_t reserve;
};

struct Inventory {
    InventorySlot slots[6];
    uint8_t       active_slot;

    InventorySlot* active() { return &slots[active_slot]; }
};

// --- Entity hierarchy ---

class Entity {
public:
    uint32_t    id;
    EntityType  type;
    EntityFlags flags;
    Vec3        position;
    Vec3        velocity;
    float       yaw, pitch;
    int32_t     health;
    int32_t     max_health;
    uint8_t     team;

    Entity() : id(0), type(EntityType::Unknown), flags{}, position{}, velocity{},
               yaw(0), pitch(0), health(0), max_health(0), team(0) {}
    virtual ~Entity() = default;

    virtual void update(float dt) {
        position = position + Vec3{velocity.x * dt, velocity.y * dt, velocity.z * dt};
    }

    virtual int32_t get_health() const { return health; }

    virtual void take_damage(int32_t amount) {
        if (flags.invulnerable) return;
        health -= amount;
        if (health <= 0) {
            health = 0;
            flags.alive = 0;
        }
    }

    virtual const char* get_name() const { return "entity"; }

    float distance_sq(const Entity& other) const {
        Vec3 d = position - other.position;
        return d.length_sq();
    }
};

class Player : public Entity {
public:
    Inventory inventory;
    uint32_t  score;
    float     view_height;
    char      name[32];

    Player() : inventory{}, score(0), view_height(64.0f) {
        type = EntityType::Player;
        max_health = 100;
        health = 100;
        flags.alive = 1;
        flags.visible = 1;
        strncpy(name, "unnamed", sizeof(name));
    }

    void update(float dt) override {
        if (!flags.alive) return;
        Entity::update(dt);
        if (position.z < 0) {
            position.z = 0;
            velocity.z = 0;
            flags.on_ground = 1;
        }
    }

    const char* get_name() const override { return name; }
};

class NPC : public Entity {
public:
    Entity*  target;
    float    aggro_range;
    float    attack_cooldown;
    float    cooldown_timer;

    NPC() : target(nullptr), aggro_range(500.0f), attack_cooldown(1.0f),
            cooldown_timer(0) {
        type = EntityType::NPC;
        max_health = 50;
        health = 50;
        flags.alive = 1;
        flags.visible = 1;
    }

    void update(float dt) override {
        if (!flags.alive) return;
        Entity::update(dt);
        cooldown_timer -= dt;
        if (target && target->flags.alive) {
            float dist = distance_sq(*target);
            if (dist < aggro_range * aggro_range && cooldown_timer <= 0) {
                target->take_damage(10);
                cooldown_timer = attack_cooldown;
            }
        }
    }

    const char* get_name() const override { return "npc"; }
};

// --- Global entity list ---

static Entity* g_entities[64];
static int     g_entity_count = 0;

Entity* find_entity(uint32_t id) {
    for (int i = 0; i < g_entity_count; i++) {
        if (g_entities[i] && g_entities[i]->id == id)
            return g_entities[i];
    }
    return nullptr;
}

// --- Jump table: entity type dispatch ---

static void process_entity(Entity* e) {
    switch (e->type) {
    case EntityType::Player:
        printf("player %s hp=%d\n", e->get_name(), e->get_health());
        break;
    case EntityType::NPC:
        printf("npc hp=%d\n", e->get_health());
        break;
    case EntityType::Projectile:
        printf("projectile at %.1f %.1f %.1f\n", e->position.x, e->position.y, e->position.z);
        break;
    case EntityType::Pickup:
        printf("pickup\n");
        break;
    case EntityType::Trigger:
        printf("trigger\n");
        break;
    default:
        printf("unknown entity type %d\n", (int)e->type);
        break;
    }
}

// --- Weapon function pointer table ---

struct WeaponDef {
    const char* name;
    int32_t     damage;
    float       fire_rate;
    float       range;
    void        (*fire)(Entity* shooter, const Vec3& dir);
};

static void fire_hitscan(Entity* shooter, const Vec3& dir) {
    printf("%s fires hitscan\n", shooter->get_name());
}

static void fire_projectile(Entity* shooter, const Vec3& dir) {
    printf("%s fires projectile\n", shooter->get_name());
}

static WeaponDef g_weapons[] = {
    {"Fists",   15,  0.5f,   3.0f, nullptr},
    {"Pistol",  25,  0.3f, 100.0f, fire_hitscan},
    {"Shotgun", 80,  1.0f,  20.0f, fire_hitscan},
    {"Rifle",   30,  0.1f, 200.0f, fire_hitscan},
    {"Sniper",  100, 1.5f, 500.0f, fire_hitscan},
    {"Rocket",  120, 2.0f, 300.0f, fire_projectile},
};

// --- XOR-encrypted string ---

static const uint8_t xor_key = 0x5A;

static char g_encrypted_server[] = {
    'G'^0x5A, 'a'^0x5A, 'm'^0x5A, 'e'^0x5A, 'S'^0x5A, 'e'^0x5A,
    'r'^0x5A, 'v'^0x5A, 'e'^0x5A, 'r'^0x5A, '#'^0x5A, '1'^0x5A, 0
};

static char* decrypt_string(char* buf, const char* enc, uint8_t key) {
    int i = 0;
    while (enc[i]) {
        buf[i] = enc[i] ^ key;
        i++;
    }
    buf[i] = 0;
    return buf;
}

// --- Checksum ---

static uint32_t checksum_region(const void* ptr, size_t len) {
    const uint8_t* data = (const uint8_t*)ptr;
    uint32_t sum = 0xDEADBEEF;
    for (size_t i = 0; i < len; i++) {
        sum ^= data[i];
        sum = (sum << 7) | (sum >> 25);
        sum += 0x1337;
    }
    return sum;
}

// --- Simulation tick ---

static void tick(float dt) {
    for (int i = 0; i < g_entity_count; i++) {
        if (g_entities[i])
            g_entities[i]->update(dt);
    }
}

// --- main ---

int main() {
    Player p1, p2;
    p1.id = 1; strncpy(p1.name, "alice", 32);
    p1.position = {100, 200, 0};
    p1.team = 1;
    p1.inventory.slots[0] = {WeaponId::Rifle, 30, 90};
    p1.inventory.active_slot = 0;

    p2.id = 2; strncpy(p2.name, "bob", 32);
    p2.position = {110, 205, 0};
    p2.team = 2;

    NPC npc1;
    npc1.id = 3;
    npc1.position = {150, 200, 0};
    npc1.target = &p2;

    g_entities[0] = &p1;
    g_entities[1] = &p2;
    g_entities[2] = &npc1;
    g_entity_count = 3;

    // decrypt server name
    char server[32];
    decrypt_string(server, g_encrypted_server, xor_key);
    printf("server: %s\n", server);

    // integrity check on weapon table
    uint32_t wep_checksum = checksum_region(g_weapons, sizeof(g_weapons));
    printf("weapon table checksum: %08x\n", wep_checksum);

    // simulate
    for (int i = 0; i < 10; i++) {
        tick(0.016f);
    }

    // fire weapon
    auto* slot = p1.inventory.active();
    auto& wep = g_weapons[(int)slot->weapon];
    if (wep.fire) {
        Vec3 dir = {1, 0, 0};
        wep.fire(&p1, dir);
    }

    // dump entities
    for (int i = 0; i < g_entity_count; i++) {
        process_entity(g_entities[i]);
    }

    printf("p2 distance from p1: %.2f\n", p1.distance_sq(p2));
    printf("net state size: %zu\n", sizeof(NetEntityState));

    return 0;
}
