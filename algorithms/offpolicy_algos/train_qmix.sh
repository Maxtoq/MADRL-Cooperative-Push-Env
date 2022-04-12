#!/bin/sh
n_run=1
env="coop_push_scenario/coop_push_scenario_sparse.py"
algorithm_name="qmix"
model_name="qmix_fo_abs_disc_shaped"
sce_conf_path="configs/2a_1o_abs.json"
cuda_device="cuda:0"
n_episodes=100000
n_exploration_eps=100000
n_updates=100000
hidden_dim=64
n_rollout_threads=1
batch_size=512
epsilon_decay_fn="exp"
epsilon_start=1.0
lr=0.0005

for n in $(seq 1 $n_run)
do
    printf "Run ${n}/${n_run}\n"
    seed=$RANDOM
    comm="python algorithms/offpolicy_algos/train2.py --env_path ${env} 
--algorithm_name ${algorithm_name} --model_name ${model_name} \
--sce_conf_path ${sce_conf_path} --seed ${seed} --use_per --n_episodes ${n_episodes} \
--epsilon_anneal_time ${n_exploration_eps} --n_updates ${n_updates} \
--hidden_dim ${hidden_dim} --n_rollout_threads ${n_rollout_threads} \
--batch_size ${batch_size} --epsilon_decay_fn ${epsilon_decay_fn} \
--epsilon_start ${epsilon_start} --lr ${lr} --cuda_device ${cuda_device}"
    printf "Starting training with command:\n${comm}\n\nSEED IS ${seed}\n"
    eval $comm
    printf "DONE\n\n"
done

