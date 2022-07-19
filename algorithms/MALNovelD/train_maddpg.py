import argparse
import os
import sys 
import torch
import numpy as np

from tensorboardX import SummaryWriter

from model.modules.maddpg import MADDPG
from utils.buffer import ReplayBuffer
from utils.make_env import get_paths, load_scenario_config, make_env


def run(cfg):
    # Get paths for saving logs and model
    run_dir, model_cp_path, log_dir = get_paths(config)
    print("Saving model in dir", run_dir)

    # Save args in txt file
    with open(os.path.join(run_dir, 'args.txt'), 'w') as f:
        f.write(str(sys.argv))

    # Init summary writer
    logger = SummaryWriter(str(log_dir))

    # Load scenario config
    sce_conf = load_scenario_config(config, run_dir)

    torch.manual_seed(config.seed)
    np.random.seed(config.seed)

    # Set training device
    if torch.cuda.is_available():
        if config.cuda_device is None:
            training_device = 'cuda'
        else:
            training_device = torch.device(config.cuda_device)
    else:
        training_device = 'cpu'

    if cfg.n_exploration_frames is None:
        cfg.n_exploration_frames = cfg.n_frames

    env = make_env(cfg.env_path, sce_conf, cfg.discrete_action)

    n_agents = sce_conf["nb_agents"]
    input_dim = env.observation_space[0].shape[0]
    if cfg.discrete_action:
        act_dim = env.action_space[0].n
    else:
        act_dim = env.action_space[0].shape[0]
    maddpg = MADDPG(n_agents, input_dim, act_dim, cfg.lr, cfg.gamma, cfg.tau,
                    cfg.hidden_dim, cfg.discrete_action, cfg.shared_params, 
                    cfg.init_explo_rate, cfg.explo_strat)
    
    replay_buffer = ReplayBuffer(
        cfg.buffer_length, 
        n_agents,
        [obsp.shape[0] for obsp in env.observation_space],
        [acsp.shape[0] if not cfg.discrete_action else acsp.n
            for acsp in env.action_space]
    )

    print(f"Starting training for {cfg.n_frames} frames")
    print(f"                  updates every {cfg.frames_per_update} frames")
    print(f"                  with seed {cfg.seed}")
    train_data_dict = {
        "Step": [],
        "Episode return": [],
        "Success": [],
        "Episode length": []
    }
    




if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--env_path", type=str, help="Path to the environment",
                    default="coop_push_scenario/coop_push_scenario_sparse.py")
    parser.add_argument("--model_name", type=str, default="TEST",
                        help="Name of directory to store model/training contents")
    parser.add_argument("--seed", default=1, type=int, help="Random seed")
    # Environment
    parser.add_argument("--episode_length", default=100, type=int)
    parser.add_argument("--discrete_action", action='store_true')
    parser.add_argument("--sce_conf_path", type=str, 
                        default="configs/2a_1o_fo_rel.json",
                        help="Path to the scenario config file")
    # Training
    parser.add_argument("--n_rollout_threads", default=1, type=int)
    parser.add_argument("--n_frames", default=100000, type=int,
                        help="Number of training frames to perform")
    parser.add_argument("--buffer_length", default=int(1e6), type=int)
    parser.add_argument("--frames_per_update", default=100, type=int)
    parser.add_argument("--batch_size", default=512, type=int,
                        help="Batch size for model training")
    parser.add_argument("--n_exploration_frames", default=None, type=int,
                        help="Number of frames where agents explore, if None then equal to n_frames")
    parser.add_argument("--explo_strat", default="sample", type=str)
    parser.add_argument("--init_explo_rate", default=1.0, type=float)
    parser.add_argument("--final_noise_scale", default=0.0, type=float)
    parser.add_argument("--save_interval", default=100000, type=int)
    # Model hyperparameters
    parser.add_argument("--hidden_dim", default=64, type=int)
    parser.add_argument("--lr", default=0.0007, type=float)
    parser.add_argument("--tau", default=0.01, type=float)
    parser.add_argument("--gamma", default=0.99, type=float)
    parser.add_argument("--shared_params", action='store_true')
    # Cuda
    parser.add_argument("--cuda_device", default=None, type=str)

    config = parser.parse_args()

    run(config)