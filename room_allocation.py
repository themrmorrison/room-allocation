import pandas as pd
from ortools.sat.python import cp_model
import sys
import math

# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------
FILE_PATH = 'excursion_data.xlsx'
FORM_TAB = 'Form Responses 1'
ROOMS_TAB = 'Rooms'
CONSTRAINTS_TAB = 'Constraints'
TIME_LIMIT_SECONDS = 15.0

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
    name_col = next((col for col in df_prefs.columns if 'name' in col.lower() or 'who' in col.lower()), None)
    gender_col = next((col for col in df_prefs.columns if 'boy' in col.lower() or 'girl' in col.lower() or 'gender' in col.lower()), None)
    friend_cols = [col for col in df_prefs.columns if 'friend' in col.lower() or 'choice' in col.lower()]

    if not name_col:
        raise ValueError("❌ Could not find a column for Student Names. Add 'Name' to the question title.")
    if not gender_col:
        raise ValueError("❌ Could not find a column for Gender. Add 'Gender' or 'Boy/Girl' to the question title.")
    if not friend_cols:
        raise ValueError("❌ Could not find Friend choice columns. Add 'Friend' or 'Choice' to those question titles.")

    # Clean student names and build gender dictionary
    students = []
    student_genders = {}
    for _, row in df_prefs.iterrows():
        if pd.notna(row[name_col]):
            s_name = str(row[name_col]).strip()
            s_gender = str(row[gender_col]).strip().lower() if pd.notna(row[gender_col]) else 'unknown'
            students.append(s_name)
            student_genders[s_name] = s_gender
            
    # Remove duplicates just in case a student submitted twice
    students = list(set(students))

    # Parse Friend Requests (Weight: 1st choice = 3, 2nd = 2, etc.)
    friend_requests = []
    for _, row in df_prefs.iterrows():
        if pd.notna(row[name_col]):
            s1 = str(row[name_col]).strip()
            # Assign weights dynamically based on how many friend columns exist
            for i, col in enumerate(friend_cols):
                weight = max(1, len(friend_cols) - i) 
                if pd.notna(row[col]):
                    s2 = str(row[col]).strip()
                    if s2 in students and s1 != s2: # Only count if friend is actually on the trip
                        friend_requests.append((s1, s2, weight))

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

    # ---------------------------------------------------------
    # 4. BUILD THE OR-TOOLS MODEL
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

    # D. Pairwise Gender Segregation (No boys and girls in same room, EVER)
    for i, s1 in enumerate(students):
        for j, s2 in enumerate(students):
            if i < j:
                if student_genders[s1] != student_genders[s2]:
                    for r in rooms:
                        model.AddAtMostOne([x[(s1, r)], x[(s2, r)]])

    # E. Pre-Assigned Room Genders (Optional)
    for s in students:
        s_gender = student_genders[s]
        for r, details in rooms.items():
            r_gender = details['gender']
            if r_gender and r_gender != s_gender:
                model.Add(x[(s, r)] == 0) # Block assignment

    # F. Objective: Maximize Friend Requests
    objective_terms = []
    for s1, s2, weight in friend_requests:
        for r in rooms:
            together_in_r = model.NewBoolVar(f'{s1}_{s2}_together_{r}')
            model.AddImplication(together_in_r, x[(s1, r)])
            model.AddImplication(together_in_r, x[(s2, r)])
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
        print(f"Total Preference Score: {solver.ObjectiveValue()}\n")
        print("-" * 40)
        
        for r, details in rooms.items():
            assigned = [s for s in students if solver.Value(x[(s, r)]) == 1]
            if assigned:
                r_gender_label = details['gender'].upper() if details['gender'] else "Flexible"
                print(f"🏠 {r} ({len(assigned)}/{details['capacity']} beds) [{r_gender_label}]:")
                for s in assigned:
                    print(f"   - {s} ({student_genders[s]})")
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
      
