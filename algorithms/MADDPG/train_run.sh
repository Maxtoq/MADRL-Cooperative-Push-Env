#!/bin/sh
n_run=10
env="coop_push_scenario/coop_push_scenario_closed.py"
model_name="2addpg_fo_abs_cont_distrew"
sce_conf_path="configs/2a_1o_fo_abs_distrew.json"
n_episodes=300000
n_exploration_eps=300000
n_updates=20000
lr=0.005
hidden_dim=64
n_rollout_threads=15

for n in $(seq 1 $n_run)
do
    printf "Run ${n}/${n_run}\n"
    seed=$RANDOM
    comm="python algorithms/MADDPG/train.py ${env} ${model_name} --sce_conf_path ${sce_conf_path} --seed ${seed} \
    --n_episodes ${n_episodes} --n_exploration_eps ${n_exploration_eps} --n_updates ${n_updates} \
    --lr ${lr} --hidden_dim ${hidden_dim} --n_rollout_threads ${n_rollout_threads}"
    printf "Starting training with command:\n${comm}\n\nSEED IS ${seed}\n"
    eval $comm
    printf "DONE\n\n"
done

