#!/bin/sh
n_run=11
env="coop_push_scenario/coop_push_scenario_sparse.py"
model_name="mymaddpg_fo_rel_disc_egreedy"
sce_conf_path="configs/2a_1o_fo_rel.json"
n_frames=10000000
buffer_length=1000000
lr=0.0007
gamma=0.99
tau=0.01
explo_strat="e_greedy"
init_explo_rate=1.0
frames_per_update=100
eval_every=100000
eval_scenar_file="eval_scenarios/hard_corners_24.json"
cuda_device="cuda:3"

for n in $(seq 1 $n_run)
do
    printf "Run ${n}/${n_run}\n"
    seed=$RANDOM
    comm="python algorithms/MALNovelD/train_maddpg.py --env_path ${env} \
--model_name ${model_name} --sce_conf_path ${sce_conf_path} --seed ${seed} \
--n_frames ${n_frames} --lr ${lr} --cuda_device ${cuda_device} --gamma ${gamma} \
--tau ${tau} --explo_strat ${explo_strat} --init_explo_rate ${init_explo_rate} \
--buffer_length ${buffer_length} --eval_every ${eval_every} \
--eval_scenar_file ${eval_scenar_file} --frames_per_update ${frames_per_update} \
--discrete_action"
    printf "Starting training with command:\n${comm}\n\nSEED IS ${seed}\n"
    eval $comm
    printf "DONE\n\n"
done
