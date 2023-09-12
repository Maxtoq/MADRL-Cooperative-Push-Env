import copy
import torch
import numpy as np

from torch import nn

from .modules.lang_learner import LanguageLearner
from .modules.comm_policy import PerfectComm
from .policy.mappo_contextinobs.mappo import MAPPO
from .policy.mappo_contextinobs.utils import get_shape_from_obs_space


class LMC:
    """
    Language-Memory for Communication using a pre-defined discrete language.
    """
    def __init__(self, args, n_agents, obs_space, shared_obs_space, act_space, 
                 vocab, device):
        self.args = args
        self.n_agents = n_agents
        self.context_dim = args.context_dim
        self.n_parallel_envs = args.n_parallel_envs
        self.n_warmup_steps = args.n_warmup_steps
        self.device = device

        # Modules
        self.lang_learner = LanguageLearner(
            obs_space[0].shape[0], 
            self.context_dim, 
            args.lang_hidden_dim, 
            vocab, 
            device,
            args.lang_lr,
            args.lang_n_epochs,
            args.lang_batch_size)

        if args.comm_policy_algo == "perfect_comm":
            self.comm_policy = PerfectComm(self.lang_learner)
        elif args.comm_policy_algo == "no_comm":
            self.comm_policy = None
            self.context_dim = 0
        else:
            raise NotImplementedError("Bad name given for communication policy algo.")


        if args.policy_algo == "mappo":
            obs_dim = get_shape_from_obs_space(obs_space[0])
            shared_obs_dim = get_shape_from_obs_space(shared_obs_space[0])
            self.policy = MAPPO(
                args, n_agents, obs_dim + self.context_dim, 
                shared_obs_dim + self.context_dim,
                act_space[0], device)

        self.message_context = np.zeros((self.n_parallel_envs, self.context_dim))

    def prep_training(self):
        self.lang_learner.prep_training()
        self.policy.prep_training()

    def prep_rollout(self, device=None):
        self.lang_learner.prep_rollout(device)
        self.policy.prep_rollout(device)

    def _make_obs(self, obs, eval_message_context=None):
        if eval_message_context is not None:
            message_context = eval_message_context
        else:
            message_context = self.message_context
        n_parallel_envs = obs.shape[0]
        shared_obs = np.concatenate(
            (obs.reshape(n_parallel_envs, -1), message_context), 
            axis=-1)
        obs = np.concatenate(
            (obs, message_context.reshape(
                n_parallel_envs, 1, self.context_dim).repeat(
                    self.n_agents, axis=1)), 
            axis=-1)
        return obs, shared_obs

    def start_episode(self, obs, eval_message_context=None):
        obs, shared_obs = self._make_obs(obs, eval_message_context)
        self.policy.start_episode(obs, shared_obs)

    def comm_n_act(self, obs, perfect_messages=None, eval_message_context=None):
        # Get actions
        values, actions, action_log_probs, rnn_states, rnn_states_critic = \
            self.policy.get_actions()
        # Get messages
        if self.comm_policy is not None:
            broadcasts, next_contexts = self.comm_policy.comm_step(
                obs, perfect_messages)
            if eval_message_context is None:
                self.message_context = next_contexts
        else:
            if eval_message_context is None:
                next_contexts = self.message_context
            else:
                next_contexts = eval_message_context
            broadcasts = []

        return values, actions, action_log_probs, rnn_states, \
               rnn_states_critic, broadcasts, next_contexts

    def reset_context(self, env_dones=None):
        """
        :param env_dones (list(bool)): Done state for each parallel environment.
        """
        if env_dones is None:
            self.message_context = np.zeros((n_parallel_envs, self.context_dim))
        else:
            self.message_context = \
                self.message_context * (1 - env_dones)[..., np.newaxis]

    def store_exp(self, obs, rewards, dones, infos, values, 
            actions, action_log_probs, rnn_states, rnn_states_critic):
        obs, shared_obs = self._make_obs(obs)
        self.policy.store(obs, shared_obs, rewards, dones, infos, values, 
            actions, action_log_probs, rnn_states, rnn_states_critic)

    def store_language_inputs(self, obs, parsed_obs):
        obs = obs.reshape(-1, obs.shape[-1])
        parsed_obs = [
            sent for env_sent in parsed_obs for sent in env_sent 
            if len(sent) > 0]
        self.lang_learner.store(obs, parsed_obs)

    def train(self, step):
        self.prep_training()
        # Train policy
        warmup = step < self.n_warmup_steps
        pol_losses = self.policy.train(warmup)
        # Train language
        if self.comm_policy is not None:
            lang_losses = self.lang_learner.train()
            return pol_losses, lang_losses
        else:
            return pol_losses

    def save(self, path):
        save_dict = self.policy.get_save_dict()
        save_dict.update(self.lang_learner.get_save_dict())
        if self.comm_policy is not None:
            save_dict.update(self.comm_policy.get_save_dict())
        torch.save(save_dict, path)
