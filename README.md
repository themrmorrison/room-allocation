# School Excursion Room Allocator

This Python tool automatically sorts students into rooms for overnight excursions. It guarantees that hard rules (room sizes, gender splits, teacher constraints) are perfectly respected, while using advanced Constraint Programming (Google OR-Tools) to maximize the number of granted friend requests.

## Prerequisites & Installation

To avoid interfering with other Python projects on your laptop, it is best practice to run this inside a **Virtual Environment (venv)**.

1. **Open Command Prompt** (Press `Win + R`, type `cmd`, and press Enter).
2. **Navigate to your project folder** where you saved the script:
   ```cmd
   cd path\to\your\folder
   ```
3. **Create the virtual environment:**
   ```cmd
   python -m venv venv
   ```
4. **Activate the virtual environment:**
   ```cmd
   venv\Scripts\activate
   ```
   *(Note: If you are using PowerShell and get an "Execution Policy" error, use standard Command Prompt `cmd` instead, as department laptops often block PowerShell scripts).*
5. **Install the required libraries:**
   ```cmd
   pip install pandas openpyxl ortools
   ```

## Data Setup Instructions

All data must be stored in a local Excel file named **`excursion_data.xlsx`**. Ensure it is in the exact same folder as the Python script.

The Excel file must have exactly these **three tabs**:

### Tab 1: `Form Responses 1`
*This is the raw output downloaded directly from Google Forms.*
* **Names:** Must contain a column with "Name" in the header. (e.g., *Student Name*). Use dropdowns in your Form to prevent typos!
* **Gender:** Must contain a column with "Gender", "Boy", or "Girl" in the header. (e.g., *Are you a Boy or a Girl?*).
* **Friends:** Must contain columns with "Friend" or "Choice" in the header. (e.g., *Friend Choice 1*, *Friend Choice 2*).

### Tab 2: `Rooms`
Defines the available beds.
* **Column A (Room Name):** e.g., *Cabin 1*
* **Column B (Capacity):** e.g., *4*
* **Column C (Gender) [OPTIONAL]:** Add "Gender" to the header. Type *Boy* or *Girl* to lock that room to a specific gender (e.g., if it's in the boys' cabin block). Leave blank if the room is flexible. *Note: Even if flexible, the algorithm will never put boys and girls in the same room.*

### Tab 3: `Constraints`
Manual teacher overrides.
* **Column A (Student 1):** Exact name matching the form.
* **Column B (Student 2):** Exact name matching the form.
* **Column C (Type):** Type exactly **Must Be Together** or **Must Be Apart**.

## How to Run

1. Ensure your virtual environment is active (you should see `(venv)` at the start of your command prompt line). 
2. Run the script:
   ```cmd
   python room_allocation.py
   ```

## Troubleshooting

If the script outputs **"❌ No mathematical solution could be found"**, it means your hard rules are mathematically impossible to solve. Check for:
1. **Bed Counts:** Ensure you have enough total *Boy* beds for the boys, and *Girl* beds for the girls.
2. **Chain Reactions:** If Alice must be with Bob, Bob must be with Charlie, and Charlie must be with David, but room capacity is only 3, the script will fail.
3. **Over-separation:** If you mark 6 boys as "Must Be Apart", but only have 5 boy rooms available to them, it cannot be solved.