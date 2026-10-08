#!/bin/bash
#SBATCH --job-name=m2_fetch
#SBATCH --output=/work/hdd/bdpr/vmattoo2/tor-shadow/logs/m2_fetch_%j.out
#SBATCH --partition=cpu
#SBATCH --account=bdpr-delta-cpu
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8GB
#SBATCH --time=01:30:00
bash /work/hdd/bdpr/vmattoo2/tor-shadow/repo/shadow/scripts/m2_fetch.sh
