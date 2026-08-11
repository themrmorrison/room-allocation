import pandas as pd
from ortools.sat.python import cp_model
import sys
import math
import re

# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------
FILE_PATH = 'excursion_data.xlsx'
FORM_TAB = 'Form responses 1'
ROOMS_TAB = 'Rooms'
CONSTRAINTS_TAB = 'Constraints'
TIME_LIMIT_SECONDS = 120.0

def normalize_name(name):
    return re.sub(r'\s+', ' ', str(name).strip()).lower()

def main():
    print("Loading data from Excel...")
    try:
        df_prefs = pd.read_excel(FILE_PATH, sheet_name=FORM_TAB)
        df_rooms = pd.read_excel(FILE_PATH, sheet_name=ROOMS_TAB)
        df_constraints = pd.read_excel(FILE_PATH, sheet_name=CONSTRAINTS_TAB)
    except FileNotFoundError:
        print(f"❌ Error: Could not find '{FILE_PATH}' in the current folder.")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error loading Excel tabs. Ensure tabs are named '{FORM_TAB}', '{ROOMS_TAB}', and '{CONSTRAINTS_TAB}'.")
        sys.exit(1)

    # ---------------------------------------------------------
    # 1. PARSE & VALIDATE: FORM RESPONSES
    # ---------------------------------------------------------
    # Collect all name columns — the sheet has one per gender section (pandas suffixes duplicates with .1, .2, …)
    name_cols = [col for col in df_prefs.columns if 'name' in col.lower() or 'who' in col.lower()]
    gender_col = next((col for col in df_prefs.columns if 'boy' in col.lower() or 'girl' in col.lower() or 'gender' in col.lower()), None)
    friend_cols = [col for col in df_prefs.columns if 'friend' in col.lower() or 'choice' in col.lower()]

    print(f"  Name columns found ({len(name_cols)}): {name_cols}")
    print(f"  Gender column: {gender_col}")
    print(f"  Friend columns found ({len(friend_cols)}): {friend_cols}")

    if not name_cols:
        raise ValueError("❌ Could not find a column for Student Names. Add 'Name' to the question title.")
    if not gender_col:
        raise ValueError("❌ Could not find a column for Gender. Add 'Gender' or 'Boy/Girl' to the question title.")
    if not friend_cols:
        raise ValueError("❌ Could not find Friend choice columns. Add 'Friend' or 'Choice' to those question titles.")

    # Clean student names and build gender dictionary
    students = []
    student_genders = {}
    for _, row in df_prefs.iterrows():
        # Resolve name from whichever name column has data for this row
        s_name = next((str(row[c]).strip() for c in name_cols if pd.notna(row[c])), None)
        if s_name is None:
            continue
        s_gender = str(row[gender_col]).strip().lower() if pd.notna(row[gender_col]) else 'unknown'
        students.append(s_name)
        student_genders[s_name] = s_gender

    # Remove duplicates just in case a student submitted twice
    students = list(dict.fromkeys(students))
    normalized_name_groups = {}
    for s in students:
        normalized_name_groups.setdefault(normalize_name(s), []).append(s)
    student_lookup = {normalized: originals[0] for normalized, originals in normalized_name_groups.items()}
    for normalized, originals in normalized_name_groups.items():
        if len(originals) > 1:
            print(f"  ⚠️ Name normalization collision for {originals}. Using {student_lookup[normalized]!r} for matching.")

    gender_counts = {}
    for g in student_genders.values():
        gender_counts[g] = gender_counts.get(g, 0) + 1
    print(f"  Students loaded: {len(students)} total — " + ", ".join(f"{g}: {n}" for g, n in sorted(gender_counts.items())))

    # Parse Friend Requests (friends are comma-separated within each cell)
    friend_requests = []
    for _, row in df_prefs.iterrows():
        s1_raw = next((str(row[c]).strip() for c in name_cols if pd.notna(row[c])), None)
        if s1_raw is None:
            continue
        s1 = student_lookup.get(normalize_name(s1_raw))
        if not s1:
            continue
        for col in friend_cols:
            if pd.notna(row[col]):
                for s2_raw in [name.strip() for name in re.split(r'[,;\n]+', str(row[col]))]:
                    if not s2_raw:
                        continue
                    s2 = student_lookup.get(normalize_name(s2_raw))
                    if s2 and s1 != s2:  # only count if friend is actually on the trip
                        friend_requests.append((s1, s2, 1))

    print(f"  Friend requests parsed: {len(friend_requests)}")

    # ---------------------------------------------------------
    # 2. PARSE: ROOMS
    # ---------------------------------------------------------
    room_gender_col = next((col for col in df_rooms.columns if 'gender' in col.lower() or 'boy' in col.lower()), None)
    
    rooms = {}
    total_capacity = 0
    for _, row in df_rooms.iterrows():
        if pd.notna(row.iloc[0]): # Ensure room name exists
            r_name = str(row.iloc[0]).strip()
            capacity = int(row.iloc[1])
            total_capacity += capacity
            
            r_gender = None
            if room_gender_col and pd.notna(row[room_gender_col]):
                r_gender = str(row[room_gender_col]).strip().lower()
                
            rooms[r_name] = {'capacity': capacity, 'gender': r_gender}
            print(f"  Room: {r_name!r} — capacity {capacity}, gender: {r_gender or 'flexible'}")

    print(f"  Total beds: {total_capacity}")
    if len(students) > total_capacity:
        raise ValueError(f"❌ Not enough beds! {len(students)} students, but only {total_capacity} beds.")

    # ---------------------------------------------------------
    # 3. PARSE: CONSTRAINTS
    # ---------------------------------------------------------
    must_together, must_apart = [], []
    for _, row in df_constraints.iterrows():
        if pd.notna(row.iloc[0]) and pd.notna(row.iloc[1]) and pd.notna(row.iloc[2]):
            s1 = str(row.iloc[0]).strip()
            s2 = str(row.iloc[1]).strip()
            c_type = str(row.iloc[2]).strip().lower()
            
            # Safeguard: only apply if both students actually exist
            if s1 in students and s2 in students:
                if 'together' in c_type:
                    must_together.append((s1, s2))
                elif 'apart' in c_type:
                    must_apart.append((s1, s2))

    print(f"  Constraints: {len(must_together)} must-be-together, {len(must_apart)} must-be-apart")

    # ---------------------------------------------------------
    # 4. BUILD THE OR-TOOLS MODEL (OPTIMIZED)
    # ---------------------------------------------------------
    print(f"Building model for {len(students)} students and {len(rooms)} rooms...")
    model = cp_model.CpModel()
    
    # Variables
    x = {}
    for s in students:
        for r in rooms:
            x[(s, r)] = model.NewBoolVar(f'assign_{s}_{r}')

    # A. One room per student
    for s in students:
        model.AddExactlyOne([x[(s, r)] for r in rooms])

    # B. Room Capacity
    for r, details in rooms.items():
        model.Add(sum(x[(s, r)] for s in students) <= details['capacity'])

    # C. Must Together & Must Apart (Manual Teacher Constraints)
    for s1, s2 in must_together:
        for r in rooms:
            model.Add(x[(s1, r)] == x[(s2, r)])
            
    for s1, s2 in must_apart:
        for r in rooms:
            model.AddAtMostOne([x[(s1, r)], x[(s2, r)]])

    # D & E. OPTIMIZED GENDER SEGREGATION & PRE-ASSIGNED ROOM GENDERS
    # Separate students by gender first
    boys = [s for s, g in student_genders.items() if g in ['boy', 'b', 'male', 'm']]
    girls = [s for s, g in student_genders.items() if g in ['girl', 'g', 'female', 'f']]

    for r, details in rooms.items():
        r_gender = details['gender']
        
        # If pre-assigned, block opposite gender directly
        if r_gender in ['boy', 'b', 'male', 'm']:
            for g in girls:
                model.Add(x[(g, r)] == 0)
        elif r_gender in ['girl', 'g', 'female', 'f']:
            for b in boys:
                model.Add(x[(b, r)] == 0)
        else:
            # Flexible room: enforce that it cannot contain BOTH boys and girls
            has_boy = model.NewBoolVar(f'has_boy_{r}')
            has_girl = model.NewBoolVar(f'has_girl_{r}')
            
            # If any boy is in room r -> has_boy is 1
            model.AddMaxEquality(has_boy, [x[(b, r)] for b in boys] if boys else [0])
            # If any girl is in room r -> has_girl is 1
            model.AddMaxEquality(has_girl, [x[(g, r)] for g in girls] if girls else [0])
            
            # Cannot have both boys and girls in the same room
            model.AddAtMostOne([has_boy, has_girl])

    # F. Objective: Maximize Friend Requests
    objective_terms = []
    for s1, s2, weight in friend_requests:
        for r in rooms:
            together_in_r = model.NewBoolVar(f'{s1}_{s2}_together_{r}')
            # Use BoolAnd instead of Implication for tighter LP relaxation
            model.AddBoolAnd([x[(s1, r)], x[(s2, r)]]).OnlyEnforceIf(together_in_r)
            objective_terms.append(weight * together_in_r)

    model.Maximize(sum(objective_terms))

    # ---------------------------------------------------------
    # 5. SOLVE
    # ---------------------------------------------------------
    print("Solving... (This may take a few seconds)")
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = TIME_LIMIT_SECONDS
    status = solver.Solve(model)

    # ---------------------------------------------------------
    # 6. PRINT RESULTS
    # ---------------------------------------------------------
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        opt_status = "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE (Time limit reached)"
        print(f"\n✅ Solution Found! [{opt_status}]")
        print(f"Total Friend Requests Granted: {int(solver.ObjectiveValue())}\n")
        print("-" * 40)
        
        for r, details in rooms.items():
            assigned = [s for s in students if solver.Value(x[(s, r)]) == 1]
            if assigned:
                r_gender_label = details['gender'].upper() if details['gender'] else "Flexible"
                print(f"🏠 {r} ({len(assigned)}/{details['capacity']} beds) [{r_gender_label}]:")
                for s in assigned:
                    print(f"   - {s} ({student_genders[s]})")
                print()

        # Build a room lookup so we can check whether any two students share a room
        room_of = {s: r for r in rooms for s in students if solver.Value(x[(s, r)]) == 1}

        # Group requests by requester and annotate each with whether it was granted
        from collections import defaultdict
        requests_by_student = defaultdict(list)
        for s1, s2, _ in friend_requests:
            granted = room_of.get(s1) == room_of.get(s2)
            requests_by_student[s1].append((s2, granted))

        not_granted_total = sum(1 for reqs in requests_by_student.values() for _, g in reqs if not g)
        print("-" * 40)
        print(f"Friend Request Breakdown (❌ = not granted, {not_granted_total} total):\n")
        for s1 in sorted(requests_by_student):
            reqs = requests_by_student[s1]
            if any(not g for _, g in reqs):
                marks = ", ".join(f"{'✅' if g else '❌'} {s2}" for s2, g in reqs)
                print(f"  {s1}: {marks}")
        print()
    else:
        print("\n❌ No mathematical solution could be found.")
        print("This usually means your constraints contradict each other.")
        print("Check if:")
        print("  - You have enough 'Boy' beds for the total number of boys.")
        print("  - Your 'Must Be Together' loops exceed room capacities.")
        print("  - Your 'Must Be Apart' rules leave no available rooms.")

if __name__ == '__main__':
    main()
    
