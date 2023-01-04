#!/bin/sh
n_run=1
env="algorithms/MALNovelD/scenarios/coop_push_scenario_noshaping.py"
model_name="qmix_cent_e2snoveld_inv_dyn"
sce_conf_path="configs/2a_1o_fo_rel.json"
n_frames=10000000
n_explo_frames=10000000
episode_length=100 # def 100
frames_per_update=100
eval_every=1000000
eval_scenar_file="eval_scenarios/hard_corners_24.json"
init_explo_rate=0.3
epsilon_decay_fn="linear"
intrinsic_reward_mode="central"
intrinsic_reward_algo="e2snoveld"
int_reward_coeff=1.0
int_reward_decay_fn="constant"
gamma=0.99
int_rew_enc_dim=64 # def 16
int_rew_hidden_dim=128 # def 64
scale_fac=0.5 # def 0.5
int_rew_lr=0.0001 # def 0.0001
state_dim=40
optimal_diffusion_coeff=30
cuda_device="cuda:3"

for n in $(seq 1 $n_run)
do
    printf "Run ${n}/${n_run}\n"
    seed=$RANDOM
    comm="python algorithms/CIR/train_qmix.py --env_path ${env} --model_name ${model_name} --sce_conf_path ${sce_conf_path} --seed ${seed} \
--n_frames ${n_frames} --cuda_device ${cuda_device} --gamma ${gamma} --episode_length ${episode_length} --frames_per_update ${frames_per_update} \
--init_explo_rate ${init_explo_rate} --n_explo_frames ${n_explo_frames} \
--intrinsic_reward_mode ${intrinsic_reward_mode} --intrinsic_reward_algo ${intrinsic_reward_algo} \
--int_reward_coeff ${int_reward_coeff} --int_reward_decay_fn ${int_reward_decay_fn} \
--scale_fac ${scale_fac} --int_rew_lr ${int_rew_lr} --int_rew_enc_dim ${int_rew_enc_dim} --int_rew_hidden_dim ${int_rew_hidden_dim} \
--state_dim ${state_dim} --optimal_diffusion_coeff ${optimal_diffusion_coeff} --save_visited_states"
# --eval_every ${eval_every} --eval_scenar_file ${eval_scenar_file} \
    printf "Starting training with command:\n${comm}\n\nSEED IS ${seed}\n"
    eval $comm
    printf "DONE\n\n"
done
