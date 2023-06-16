import json
import time
import git
import os
import re
from pathlib import Path
from shutil import copyfile

def get_paths(cfg):
    env_name = cfg.env_name + '_' + cfg.task_name
    # Get path of the run directory
    model_dir = Path('./models') / env_name / cfg.experiment_name
    if not model_dir.exists():
        curr_run = 'run1'
    else:
        exst_run_nums = [int(str(folder.name).split('run')[1]) for folder in
                         model_dir.iterdir() if
                         str(folder.name).startswith('run')]
        if len(exst_run_nums) == 0:
            curr_run = 'run1'
        else:
            curr_run = 'run%i' % (max(exst_run_nums) + 1)
    run_dir = model_dir / curr_run
    model_cp_path = run_dir / 'model.pt'
    log_dir = run_dir / 'logs'
    if not log_dir.exists():
        os.makedirs(log_dir)

    return run_dir, model_cp_path, log_dir

def load_scenario_cfg(cfg, run_dir):
    sce_conf = {}
    if cfg.sce_conf_path is not None:
        copyfile(cfg.sce_conf_path, run_dir / 'sce_cfg.json')
        with open(cfg.sce_conf_path) as cf:
            sce_conf = json.load(cf)
            print('Special cfg for scenario:', cfg.env_path)
            print(sce_conf, '\n')
    return sce_conf

def write_params(run_directory, cfg, env=None):
    with open(os.path.join(run_directory, 'args.txt'), 'w') as f:
        f.write(str(time.time()) + '\n')
        commit_hash = git.Repo(
            search_parent_directories=True).head.object.hexsha
        f.write(
            "Running train_qmix.py at git commit " + str(commit_hash) + '\n')
        f.write("Parameters:\n")
        f.write(json.dumps(vars(cfg), indent=4))
        if env is not None:
            f.write("\nScenario parameters:\n")
            f.write(json.dumps(env.world.scenario_params, indent=4))