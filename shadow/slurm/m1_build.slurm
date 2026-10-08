#!/bin/bash
#SBATCH --job-name=m1_build
#SBATCH --output=/work/hdd/bdpr/vmattoo2/tor-shadow/logs/m1_build_%j.out
#SBATCH --partition=cpu
#SBATCH --account=bdpr-delta-cpu
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=64GB
#SBATCH --time=03:00:00
bash /work/hdd/bdpr/vmattoo2/tor-shadow/repo/shadow/scripts/m1_build.sh
