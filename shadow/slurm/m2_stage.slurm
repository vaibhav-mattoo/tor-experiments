#!/bin/bash
#SBATCH --job-name=m2_stage
#SBATCH --output=/work/hdd/bdpr/vmattoo2/tor-shadow/logs/m2_stage_%j.out
#SBATCH --partition=cpu
#SBATCH --account=bdpr-delta-cpu
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32GB
#SBATCH --time=02:00:00
bash /work/hdd/bdpr/vmattoo2/tor-shadow/repo/shadow/scripts/m2_stage.sh
