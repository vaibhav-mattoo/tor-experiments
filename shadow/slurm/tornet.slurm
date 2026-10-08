#!/bin/bash
# Usage: sbatch -J NAME -c CPUS --mem=MEM -t HH:MM:SS tornet.slurm NAME SCALE STOP_S CONVERGE_S [MODIFIER]
# (wall time must stay <= 3 h per the task's scale cap)
#SBATCH --output=/work/hdd/bdpr/vmattoo2/tor-shadow/logs/%x_%j.out
#SBATCH --partition=cpu
#SBATCH --account=bdpr-delta-cpu
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
bash /work/hdd/bdpr/vmattoo2/tor-shadow/repo/shadow/scripts/run_tornet.sh "$@"
