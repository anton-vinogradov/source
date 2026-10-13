#!/usr/bin/env python3
"""Compile a focused opponent-count regression harness from a JA2 source checkout.

Usage:
  python3 test_opponent_counts.py /path/to/source
  python3 test_opponent_counts.py /path/to/source --ref HEAD

The harness extracts the checkout's real LooseDisguise,
RecalculateOppCntsDueToNoLongerNeutral, AddOneOpponent, RemoveOneOpponent,
RemoveManAsTarget and CONSIDERED_NEUTRAL. Its fixture supplies small soldier
records and inert dependencies. RecognizeAsCombatant always returns true for
the unveiled targets used by these tests; automatic discovery is outside this
harness's scope. This is focused logic regression coverage, not a full game
build or gameplay validation. Scalar types, SoldierID, body/status enums and
range constants are read from the checkout; soldier records remain minimal.
"""

import argparse
import pathlib
import re
import subprocess
import tempfile


def extract_function(source, name):
    match = re.search(r"^[\w\t *]+\b" + re.escape(name) + r"\s*\([^;{]*\)\s*\{", source, re.M)
    if not match:
        raise ValueError(f"Cannot find definition of {name}")
    start = match.start()
    brace = source.index("{", match.start(), match.end())
    depth, index, state = 1, brace + 1, "code"
    while index < len(source):
        char = source[index]
        following = source[index:index + 2]
        if state == "line":
            if char == "\n":
                state = "code"
        elif state == "block":
            if following == "*/":
                state = "code"
                index += 1
        elif state in ('"', "'"):
            if char == "\\":
                index += 1
            elif char == state:
                state = "code"
        elif following == "//":
            state = "line"
            index += 1
        elif following == "/*":
            state = "block"
            index += 1
        elif char in ('"', "'"):
            state = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if not depth:
                return source[start:index + 1]
        index += 1
    raise ValueError(f"Unbalanced definition of {name}")


def extract_macro(source, name):
    lines = source.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^#define\s+" + re.escape(name) + r"\b", line):
            result = [line]
            while result[-1].rstrip().endswith("\\"):
                index += 1
                result.append(lines[index])
            return "\n".join(result)
    raise ValueError(f"Cannot find macro {name}")


def extract_enum_with_member(source, member):
    member_index = source.index(member)
    start = source.rfind("enum", 0, member_index)
    end = source.index("};", member_index) + 2
    if start < 0:
        raise ValueError(f"Cannot find enum containing {member}")
    return source[start:end]


FIXTURE = r'''
#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
// Source-backed scalar typedefs, enums, range macros and SoldierID are inserted.
/* SOURCE_TYPES */
constexpr int NOWHERE = -1;
#define DebugMsg(...) ((void)0)
#define ScreenMsg(...) ((void)0)
struct SOLDIERTYPE;
/* SOURCE_SOLDIER_ID */
struct SOLDIERTYPE {
    SoldierID ubID = 0;
    INT8 bTeam = OUR_TEAM, bActive = FALSE;
    UINT8 bSide = 0, bInSector = FALSE, ubBodyType = REGMALE;
    UINT32 usSoldierFlagMask = 0;
    struct { INT8 bLife = 0; } stats;
    struct { UINT32 uiStatusFlags = 0; } flags;
    struct {
        INT8 bOppCnt = 0;
        INT8 bNeutral = FALSE, bAlertStatus = STATUS_GREEN;
        SoldierID ubCaller = NOBODY;
        UINT8 bCallPriority = 0;
        std::array<INT8, TOTAL_SOLDIERS> bOppList{};
    } aiData;
    int orderChanges = 0;
    void LooseDisguise(void);
    BOOLEAN RecognizeAsCombatant(SoldierID) { return TRUE; }
};
std::array<SOLDIERTYPE, TOTAL_SOLDIERS> soldiers;
std::array<SOLDIERTYPE*, TOTAL_SOLDIERS> MercSlots{};
SOLDIERTYPE* MercPtrs[TOTAL_SOLDIERS]{};
UINT32 guiNumMercSlots = 0;
struct {
    struct {
        SoldierID bFirstID = 0, bLastID = 0, ubLastMercToRadio = NOBODY;
    } Team[MAXTEAMS];
    INT8 bConsNumTurnsNotSeen = 0;
} gTacticalStatus;
INT8 gbPlayerNum = OUR_TEAM;
INT8 gbSeenOpponents[TOTAL_SOLDIERS][TOTAL_SOLDIERS]{};
void CheckForChangingOrders(SOLDIERTYPE* s) { ++s->orderChanges; }
void UpdatePublic(int, int, int, int, int) {}
void UpdatePersonal(SOLDIERTYPE* s, int target, INT8 state, int, int) {
    s->aiData.bOppList.at(target) = state;
}
void ResetLastKnownLocs(SOLDIERTYPE*) {}
void AddOneOpponent(SOLDIERTYPE*);
void RemoveOneOpponent(SOLDIERTYPE*);
'''


TESTS = r'''
int checks = 0, failures = 0;
void check(bool condition, const std::string& description) {
    ++checks;
    if (!condition) {
        ++failures;
        std::cerr << "FAIL: " << description << '\n';
    }
}
void count_is(SOLDIERTYPE* s, int expected, const std::string& description) {
    check(s->aiData.bOppCnt == expected, description + " (expected " +
          std::to_string(expected) + ", got " + std::to_string(s->aiData.bOppCnt) + ")");
}
void reset() {
    soldiers = {};
    MercSlots = {};
    guiNumMercSlots = 0;
    gTacticalStatus = {};
    for (int id = 0; id < TOTAL_SOLDIERS; ++id) {
        soldiers[id].ubID = id;
        MercPtrs[id] = &soldiers[id];
    }
    // Default single-player allocation, using the checkout's actual maxima.
    int next = 0;
    const int sizes[] = {CODE_MAXIMUM_NUMBER_OF_PLAYER_MERCS + CODE_MAXIMUM_NUMBER_OF_PLAYER_VEHICLES,
                       CODE_MAXIMUM_NUMBER_OF_ENEMIES, CODE_MAXIMUM_NUMBER_OF_CREATURES,
                       CODE_MAXIMUM_NUMBER_OF_REBELS, CODE_MAXIMUM_NUMBER_OF_CIVS};
    for (int team = OUR_TEAM; team <= CIV_TEAM; ++team) {
        gTacticalStatus.Team[team].bFirstID = next;
        next += sizes[team];
        gTacticalStatus.Team[team].bLastID = next - 1;
    }
}
SOLDIERTYPE* living(int id, int team, int side) {
    auto* s = &soldiers.at(id);
    s->bActive = true;
    s->bInSector = true;
    s->stats.bLife = 100;
    s->bTeam = team;
    s->bSide = side;
    MercSlots.at(guiNumMercSlots++) = s;
    return s;
}
void sees(SOLDIERTYPE* a, SOLDIERTYPE* b) {
    a->aiData.bOppList.at(b->ubID) = SEEN_CURRENTLY;
}
void player_spy_fixture(bool lan, bool holes, bool reverse, bool bloodcat = false, bool high_id = false) {
    reset();
    if (lan) {
        // Actual MP ranges from Overhead.cpp: civilian IDs end before LAN teams.
        gTacticalStatus.Team[OUR_TEAM].bFirstID = 0;
        gTacticalStatus.Team[OUR_TEAM].bLastID = 19;
        gTacticalStatus.Team[CIV_TEAM].bFirstID = 85;
        gTacticalStatus.Team[CIV_TEAM].bLastID = 116;
    }
    auto* ally = living(0, OUR_TEAM, 0);
    auto* spy = living(1, OUR_TEAM, 0);
    const int enemy_id = lan ? (high_id ? 300 : 120) :
        static_cast<UINT16>(gTacticalStatus.Team[bloodcat ? CREATURE_TEAM : ENEMY_TEAM].bFirstID);
    auto* enemy = living(enemy_id,
                         bloodcat ? CREATURE_TEAM : (lan ? (high_id ? LAN_TEAM_FOUR : LAN_TEAM_ONE) : ENEMY_TEAM), 1);
    if (bloodcat) enemy->ubBodyType = BLOODCAT;
    sees(ally, enemy); sees(spy, enemy); sees(enemy, ally); sees(enemy, spy);
    ally->aiData.bOppCnt = 1;
    ally->aiData.bAlertStatus = STATUS_BLACK;
    enemy->aiData.bOppCnt = bloodcat ? 2 : 1;
    enemy->aiData.bAlertStatus = STATUS_BLACK;
    if (bloodcat) {
        // Creature neutrality semantics already count disguised human mercs.
        spy->aiData.bOppCnt = 1;
        spy->aiData.bAlertStatus = STATUS_BLACK;
    }
    spy->usSoldierFlagMask = SOLDIER_COVERT_CIV | SOLDIER_COVERT_NPC_SPECIAL;
    if (reverse) std::reverse(MercSlots.begin(), MercSlots.begin() + guiNumMercSlots);
    if (holes) {
        auto saved = MercSlots;
        MercSlots = {};
        MercSlots[1] = saved[0]; MercSlots[3] = saved[1]; MercSlots[5] = saved[2];
        guiNumMercSlots = 6;
    }
    const std::string variant = std::string(bloodcat ? "hostile bloodcat" : (lan ? "LAN" : "single-player")) +
        (high_id ? "/ID above 255" : "") + (holes ? "/holes" : "") + (reverse ? "/reverse slots" : "");
    spy->LooseDisguise();
    check(spy->usSoldierFlagMask == 0, variant + ": covert flags cleared");
    count_is(ally, 1, variant + ": existing visible enemy counted once");
    count_is(spy, 1, variant + ": newly uncovered spy counts visible enemy once");
    count_is(enemy, 2, variant + ": enemy counts both visible mercs");
    check(ally->aiData.bAlertStatus == STATUS_BLACK && ally->orderChanges == 0,
          variant + ": existing ally alert skips order callback");
    check(spy->aiData.bAlertStatus == STATUS_BLACK && spy->orderChanges == (bloodcat ? 0 : 1),
          variant + ": self rebuild invokes order callback only for previously unaware spy");
    spy->LooseDisguise();
    count_is(ally, 1, variant + ": repeated reveal is idempotent for ally");
    count_is(spy, 1, variant + ": repeated reveal is idempotent for spy");
    count_is(enemy, 2, variant + ": repeated reveal is idempotent for enemy");
    check(ally->orderChanges == 0 && spy->orderChanges == (bloodcat ? 0 : 1),
          variant + ": repeated reveal retains existing black-status order behavior");
    enemy->stats.bLife = 0;
    RemoveManAsTarget(enemy);
    count_is(ally, 0, variant + ": enemy death clears ally count");
    count_is(spy, 0, variant + ": enemy death clears spy count");
    check(ally->aiData.bOppList[enemy->ubID] == NOT_HEARD_OR_SEEN,
          variant + ": enemy death clears ally sight entry");
}
void other_target_exclusion(unsigned int flag, const std::string& name) {
    reset();
    auto* spy = living(0, OUR_TEAM, 0);
    auto* ally = living(1, OUR_TEAM, 0);
    auto* target = living(gTacticalStatus.Team[ENEMY_TEAM].bFirstID, ENEMY_TEAM, 1);
    spy->usSoldierFlagMask = SOLDIER_COVERT_CIV;
    target->usSoldierFlagMask = flag;
    sees(spy, target); sees(ally, target);
    spy->LooseDisguise();
    count_is(spy, 0, name + ": unveiled spy still excludes target");
    count_is(ally, 0, name + ": ally still excludes target");
    check(target->usSoldierFlagMask == flag, name + ": revealing another spy retains target's flags");
}
void asymmetric_sight() {
    reset();
    auto* ally = living(0, OUR_TEAM, 0);
    auto* spy = living(1, OUR_TEAM, 0);
    auto* enemy = living(gTacticalStatus.Team[ENEMY_TEAM].bFirstID, ENEMY_TEAM, 1);
    spy->usSoldierFlagMask = SOLDIER_COVERT_SOLDIER;
    sees(spy, enemy);
    sees(enemy, ally); sees(enemy, spy);
    enemy->aiData.bOppCnt = 1;
    enemy->aiData.bAlertStatus = STATUS_BLACK;
    spy->LooseDisguise();
    count_is(spy, 1, "asymmetric sight: spy counts visible enemy");
    count_is(ally, 0, "asymmetric sight: unseen enemy does not count for ally");
    count_is(enemy, 2, "asymmetric sight: enemy counts both visible mercs");
    enemy->stats.bLife = 0;
    RemoveManAsTarget(enemy);
    count_is(spy, 0, "asymmetric sight: enemy death clears spy count");
    check(ally->aiData.bOppCnt == 0 && ally->aiData.bAlertStatus == STATUS_GREEN,
          "asymmetric sight: death leaves unaware ally's count and alert unchanged");
}
void default_peer_notification() {
    reset();
    auto* civilian = living(gTacticalStatus.Team[CIV_TEAM].bFirstID, CIV_TEAM, 1);
    auto* merc = living(0, OUR_TEAM, 0);
    sees(civilian, merc); sees(merc, civilian);
    gTacticalStatus.bConsNumTurnsNotSeen = 7;
    RecalculateOppCntsDueToNoLongerNeutral(civilian);
    count_is(civilian, 1, "default single-soldier update counts caller");
    count_is(merc, 1, "default single-soldier update notifies peer");
    check(civilian->aiData.bAlertStatus == STATUS_BLACK,
          "default update retains first-opponent alert transition");
    check(civilian->orderChanges == 1, "default update retains order-change callback");
    check(gTacticalStatus.bConsNumTurnsNotSeen == 0,
          "default update retains player last-seen turn reset");
}
void visibility_and_filter_preservation() {
    reset();
    auto* spy = living(1, OUR_TEAM, 0);
    auto* inactive = living(3, OUR_TEAM, 0); inactive->bActive = false;
    auto* away = living(4, OUR_TEAM, 0); away->bInSector = false;
    auto* dead = living(5, OUR_TEAM, 0); dead->stats.bLife = 0;
    inactive->aiData.bOppCnt = 7; away->aiData.bOppCnt = 8; dead->aiData.bOppCnt = 9;
    spy->LooseDisguise();
    count_is(inactive, 7, "inactive observer remains excluded from global refresh");
    count_is(away, 8, "off-sector observer remains excluded from global refresh");
    count_is(dead, 9, "dead observer remains excluded from global refresh");
    reset();
    auto* caller = living(0, OUR_TEAM, 0);
    auto* ally = living(gTacticalStatus.Team[MILITIA_TEAM].bFirstID, MILITIA_TEAM, 0);
    auto* neutral = living(gTacticalStatus.Team[CIV_TEAM].bFirstID, CIV_TEAM, 1); neutral->aiData.bNeutral = true;
    auto* hidden = living(gTacticalStatus.Team[ENEMY_TEAM].bFirstID, ENEMY_TEAM, 1);
    caller->aiData.bOppList[hidden->ubID] = 2; // Seen previously, not currently.
    sees(caller, ally); sees(caller, neutral);
    RecalculateOppCntsDueToNoLongerNeutral(caller);
    count_is(caller, 0, "same-side, neutral and previously seen soldiers remain excluded");
    reset();
    auto* monster = living(gTacticalStatus.Team[CREATURE_TEAM].bFirstID, CREATURE_TEAM, 1);
    auto* neutral_again = living(gTacticalStatus.Team[CIV_TEAM].bFirstID, CIV_TEAM, 0); neutral_again->aiData.bNeutral = true;
    sees(monster, neutral_again);
    RecalculateOppCntsDueToNoLongerNeutral(monster);
    count_is(monster, 0, "existing direct neutral-creature exclusion is preserved");
}
void add_one_side_effects() {
    reset();
    auto* monster = living(gTacticalStatus.Team[CREATURE_TEAM].bFirstID, CREATURE_TEAM, 1);
    monster->flags.uiStatusFlags = SOLDIER_MONSTER;
    monster->aiData.ubCaller = 17;
    monster->aiData.bCallPriority = 3;
    AddOneOpponent(monster);
    check(monster->aiData.bAlertStatus == STATUS_BLACK && monster->orderChanges == 1,
          "actual AddOne retains status and order transition");
    check(monster->aiData.ubCaller == NOBODY && monster->aiData.bCallPriority == 0,
          "actual AddOne retains monster caller reset");
    auto* larva = living(static_cast<UINT16>(gTacticalStatus.Team[CREATURE_TEAM].bFirstID) + 1, CREATURE_TEAM, 1);
    larva->ubBodyType = LARVAE_MONSTER;
    AddOneOpponent(larva);
    count_is(larva, 1, "actual AddOne still increments larvae");
    check(larva->aiData.bAlertStatus == STATUS_GREEN && larva->orderChanges == 0,
          "actual AddOne retains larvae awareness exception");
}
int main() {
    player_spy_fixture(false, false, false);
    player_spy_fixture(false, false, true);
    player_spy_fixture(true, true, false);
    player_spy_fixture(true, true, true);
    player_spy_fixture(true, true, true, false, true);
    player_spy_fixture(false, false, false, true);
    other_target_exclusion(SOLDIER_POW, "POW target");
    other_target_exclusion(SOLDIER_COVERT_SOLDIER, "still-disguised other target");
    asymmetric_sight();
    default_peer_notification();
    visibility_and_filter_preservation();
    add_one_side_effects();
    std::cout << checks << " focused checks; " << failures << " failures\n";
    return failures ? 1 : 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=pathlib.Path)
    parser.add_argument("--ref", help="Read original files from this Git ref instead of working tree")
    parser.add_argument("--compiler", default="clang++")
    parser.add_argument("--work-dir", type=pathlib.Path,
                        default=pathlib.Path(__file__).resolve().parent.parent / "work")
    args = parser.parse_args()
    checkout = args.checkout.resolve()

    def read(relative):
        if args.ref:
            return subprocess.check_output(
                ["git", "-C", str(checkout), "show", f"{args.ref}:{relative}"], text=True)
        return (checkout / relative).read_text()

    opplist = read("Tactical/opplist.cpp")
    control = read("Tactical/Soldier Control.cpp")
    header = read("Tactical/Soldier Control.h")
    overhead_types = read("Tactical/Overhead Types.h")
    scalar_types = read("sgp/types.h")
    animation_data = read("Tactical/Animation Data.h")
    api = read("Tactical/opplist.h")
    declaration = re.search(
        r"void\s+RecalculateOppCntsDueToNoLongerNeutral\s*\([^;]*\)\s*;", api)
    if not declaration:
        raise ValueError("Cannot find opponent-recalculation public declaration")
    macro_names = ["SOLDIER_COVERT_CIV", "SOLDIER_COVERT_SOLDIER", "SOLDIER_COVERT_NPC_SPECIAL",
                   "SOLDIER_POW", "SOLDIER_VEHICLE", "SOLDIER_MONSTER", "SOLDIER_BOXER"]
    macros = "\n".join(extract_macro(header, name) for name in macro_names)
    range_names = ["CODE_MAXIMUM_NUMBER_OF_PLAYER_MERCS", "CODE_MAXIMUM_NUMBER_OF_PLAYER_VEHICLES",
                   "CODE_MAXIMUM_NUMBER_OF_ENEMIES", "CODE_MAXIMUM_NUMBER_OF_CREATURES",
                   "CODE_MAXIMUM_NUMBER_OF_REBELS", "CODE_MAXIMUM_NUMBER_OF_CIVS",
                   "MAX_NUM_SOLDIERS", "TOTAL_SOLDIERS", "MAXTEAMS", "OUR_TEAM", "ENEMY_TEAM",
                   "CREATURE_TEAM", "MILITIA_TEAM", "CIV_TEAM", "LAN_TEAM_ONE", "LAN_TEAM_FOUR",
                   "SEEN_CURRENTLY", "NOT_HEARD_OR_SEEN"]
    macros += "\n" + "\n".join(extract_macro(overhead_types, name) for name in range_names)
    macros += "\n" + extract_macro(scalar_types, "TRUE") + "\n" + extract_macro(scalar_types, "FALSE")
    typedefs = []
    for name in ["BOOLEAN", "UINT8", "INT8", "UINT16", "INT16", "UINT32", "INT32"]:
        match = re.search(r"^typedef[^\n;]+\b" + name + r"\s*;", scalar_types, re.M)
        if not match:
            raise ValueError(f"Cannot find source typedef for {name}")
        typedefs.append(match.group())
    source_types = "\n".join(typedefs) + "\n" + \
        extract_enum_with_member(overhead_types, "STATUS_GREEN") + "\n" + \
        extract_enum_with_member(animation_data, "LARVAE_MONSTER")
    id_start = overhead_types.index("extern SOLDIERTYPE *MercPtrs[TOTAL_SOLDIERS];")
    id_end = overhead_types.index(";", overhead_types.index("inline constexpr SoldierID NOBODY")) + 1
    source_id = overhead_types[id_start:id_end]
    fixture = FIXTURE.replace("/* SOURCE_TYPES */", source_types).replace("/* SOURCE_SOLDIER_ID */", source_id)
    macro = extract_macro(header, "CONSIDERED_NEUTRAL")
    functions = "\n\n".join([
        extract_function(opplist, "AddOneOpponent"),
        extract_function(opplist, "RemoveOneOpponent"),
        extract_function(opplist, "RecalculateOppCntsDueToNoLongerNeutral"),
        extract_function(control, "SOLDIERTYPE::LooseDisguise"),
        extract_function(opplist, "RemoveManAsTarget"),
    ])
    source = macros + "\n" + fixture + "\n" + macro + "\n" + declaration.group() + \
        "\n" + functions + "\n" + TESTS
    args.work_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="opponent-counts-", dir=args.work_dir) as temporary:
        source_path = pathlib.Path(temporary) / "test.cpp"
        binary_path = pathlib.Path(temporary) / "test"
        source_path.write_text(source)
        # RemoveManAsTarget contains a legacy nested-comment marker. Preserve
        # the source verbatim and suppress only that existing warning.
        subprocess.run([args.compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Wno-comment",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                        str(source_path), "-o", str(binary_path)], check=True)
        result = subprocess.run([str(binary_path)], check=False)
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
