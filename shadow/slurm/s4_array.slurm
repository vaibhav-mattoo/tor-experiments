#!/bin/bash
# S4: {vanilla, regretor} x seeds {1,2,3} on the S1 network. Submit with
#   sbatch --array=0-5 --export=ALL,RATE_FACTOR=<f> s4_array.slurm
# index i -> arm = (vanilla, regretor)[i % 2], seed = i / 2 + 1. 20 sim min (30 does not fit 2 h, see STATUS), 10 min warm-up.
#SBATCH --job-name=s4
#SBATCH --output=/work/hdd/bdpr/vmattoo2/tor-shadow/logs/s4_%A_%a.out
#SBATCH --partition=cpu
#SBATCH --account=bdpr-delta-cpu
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=32
#SBATCH --time=02:00:00
B=/work/hdd/bdpr/vmattoo2/tor-shadow
i=${SLURM_ARRAY_TASK_ID:?}
ARMS=(vanilla regretor); export ARM=${ARMS[$((i % 2))]}; export SSEED=$((i / 2 + 1)); export SHADOW_SEED=$SSEED
NAME=${RUNPFX:-s4}_${ARM}_s${SSEED}
mkdir -p $B/runs/$NAME && [ -d $B/runs/$NAME/gen ] || cp -r $B/runs/s1_cal/gen $B/runs/$NAME/
bash $B/repo/shadow/scripts/run_tornet.sh $NAME 0.005 ${STOP:-1200} 600 $B/repo/shadow/scripts/mod_s.sh
