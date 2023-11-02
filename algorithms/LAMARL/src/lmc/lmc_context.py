import copy
import torch
import numpy as np

from torch import nn

from .modules.lang_learner import LanguageLearner
from .modules.comm_policy_context import CommPol_Context
from .policy.mappo.mappo import MAPPO
from .policy.mappo.utils import get_shape_from_obs_space


class LMC:
    """
    Language-Memory for Communication using a pre-defined discrete language.
    """
    def __init__(self, args, n_agents, obs_space, shared_obs_space, act_space, 
                 vocab, comm_logger=None, device="cpu"):
        self.args = args
        self.n_agents = n_agents
        self.context_dim = args.context_dim
        self.n_parallel_envs = args.n_parallel_envs
        self.n_warmup_steps = args.n_warmup_steps
        self.comm_n_warmup_steps = args.comm_n_warmup_steps
        self.token_penalty = args.comm_token_penalty
        self.klpretrain_coef = args.comm_klpretrain_coef
        self.env_reward_coef = args.comm_env_reward_coef
        self.comm_logger = comm_logger
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

        # self.comm_pol_algo = args.comm_policy_algo
        # if self.comm_pol_algo == "ppo_mlp":
        #     self.comm_policy = CommPPO_MLP(args, n_agents, self.lang_learner, device)
        # elif self.comm_pol_algo == "perfect_comm":
        #     self.comm_policy = PerfectComm(self.lang_learner)
        # elif self.comm_pol_algo == "no_comm":
        #     self.comm_policy = None
        #     self.context_dim = 0
        # else:
        #     raise NotImplementedError("Bad name given for communication policy algo.")

        self.comm_policy = CommPol_Context(
            args, self.n_agents, self.lang_learner, device)

        if args.policy_algo == "mappo":
            obs_dim = get_shape_from_obs_space(obs_space[0])
            shared_obs_dim = get_shape_from_obs_space(shared_obs_space[0])
            self.policy = MAPPO(
                args, n_agents, obs_dim + self.context_dim, 
                shared_obs_dim + self.context_dim,
                act_space[0], device)

        # self.last_messages = None
        self.last_kl_penalties = None

    def prep_training(self):
        self.lang_learner.prep_training()
        self.policy.prep_training()
        if self.comm_policy is not None:
            self.comm_policy.prep_training()

    def prep_rollout(self, device=None):
        self.lang_learner.prep_rollout(device)
        self.policy.prep_rollout(device)
        if self.comm_policy is not None:
            self.comm_policy.prep_rollout(device)

    def _make_obs(self, obs, message_contexts):
        n_parallel_envs = obs.shape[0]

        shared_obs = np.concatenate(
            (obs.reshape(n_parallel_envs, -1), message_contexts), 
            axis=-1)
        obs = np.concatenate(
            (obs, message_contexts.reshape(
                n_parallel_envs, 1, self.context_dim).repeat(
                    self.n_agents, axis=1)), 
            axis=-1)
        return obs, shared_obs

    def start_episode(self):
        self.policy.start_episode()

    def comm_n_act(self, obs, lang_contexts, perfect_messages=None):
        """
        Perform a whole model step, with first a round of communication and 
        then choosing action for each agent.

        :param obs (np.ndarray): Observations for each agent in each parallel 
            environment, dim=(n_parallel_envs, n_agents, obs_dim).
        :param lang_contexts (np.ndarray): Language contexts from last step,
            dim=(n_parallel_envs, context_dim).
        :param perfect_messages (list(list(list(str)))): "Perfect" messages 
            given by the parser, default None.

        :return values (np.ndarray): Values generated by the critic, 
            dim=(n_parallel_envs, n_agents, 1).
        :return actions (np.ndarray): Values generated by the critic, 
            dim=(n_parallel_envs, n_agents, 1).
        :return action_log_probs (np.ndarray): Log-probabilities of chosen 
            actions, dim=(n_parallel_envs, n_agents, 1).
        :return rnn_states (np.ndarray): Rnn states of the policy actors, 
            dim=(n_parallel_envs, n_agents, 1, hidden_dim).
        :return rnn_states_critic (np.ndarray): Rnn states of the policy 
            critics, dim=(n_parallel_envs, n_agents, 1, hidden_dim).
        :return broadcasts (list(list(str))): List of broadcasted messages for
            each parallel environment.
        :return lang_contexts (np.ndarray): Language contexts after this step, 
            dim=(n_parallel_envs, context_dim).
        """
        # Get messages
        if self.comm_policy is not None:
            broadcasts, messages, lang_contexts, kl_penalties = \
                self.comm_policy.comm_step(
                    obs, lang_contexts, perfect_messages)
        else:
            lang_contexts = np.zeros((self.n_parallel_envs, 0))
            broadcasts = []

        # Log communication
        if self.comm_logger is not None:
            self.comm_logger.store_messages(
                obs, messages, 
                perfect_messages, 
                broadcasts, 
                kl_penalties.sum(0))

        # Save messages and kl_penalties for communication evaluation
        # self.last_messages = messages
        self.last_kl_penalties = kl_penalties

        # Store policy inputs in policy buffer
        obs, shared_obs = self._make_obs(obs, lang_contexts)
        self.policy.store_obs(obs, shared_obs)

        # Get actions
        values, actions, action_log_probs, rnn_states, rnn_states_critic = \
            self.policy.get_actions()

        return values, actions, action_log_probs, rnn_states, \
               rnn_states_critic, broadcasts, lang_contexts

    def eval_comm(self, message_rewards):
        # Log communication rewards
        if self.comm_logger is not None:
            self.comm_logger.store_rewards(message_rewards)
        # Evaluate communication
        # if self.comm_pol_algo in ["ppo_mlp"]:
        message_rewards *= self.env_reward_coef
        token_penalties = np.ones_like(
            self.last_kl_penalties) * -self.token_penalty

        token_rewards = self.klpretrain_coef * self.last_kl_penalties \
                            + token_penalties

        mean_message_return = self.comm_policy.store_rewards(
            message_rewards.flatten(), token_rewards)

        return mean_message_return

    def train_comm(self, step):
        warmup = step < self.comm_n_warmup_steps
        return self.comm_policy.train(warmup)

    def reset_context(self, current_lang_contexts=None, env_dones=None):
        """
        Returns reset language contexts.
        :param current_lang_contexts (np.ndarray): default None, if not 
            provided return zero-filled contexts, if provided return contexts
            with zeros where the env is done.
        :param env_dones (np.ndarray): Done state for each parallel environment,
            default None, must be provided if current_lang_contexts is.

        :return lang_contexts (np.ndaray): new language contexts.
        """
        if current_lang_contexts is None:
            return np.zeros(
                (self.n_parallel_envs, self.context_dim), dtype=np.float32)
        else:
            assert env_dones is not None, "env_dones must be provided if current_lang_contexts is."
            return current_lang_contexts * (1 - env_dones).astype(
                np.float32)[..., np.newaxis]

    def store_exp(self, rewards, dones, infos, values, 
            actions, action_log_probs, rnn_states, rnn_states_critic):
        self.policy.store_act(
            rewards, dones, infos, values, actions, action_log_probs, 
            rnn_states, rnn_states_critic)

    def store_language_inputs(self, obs, parsed_obs):
        obs = obs.reshape(-1, obs.shape[-1])
        parsed_obs = [
            sent for env_sent in parsed_obs for sent in env_sent]
        self.lang_learner.store(obs, parsed_obs)

    def train(self, step, train_lang=True):
        self.prep_training()
        # Train policy
        warmup = step < self.n_warmup_steps
        pol_losses = self.policy.train(warmup)
        # TODO Add train comm_pol
        # Train language
        if self.comm_policy is not None and train_lang:
            lang_losses = self.lang_learner.train()
            return pol_losses, lang_losses
        else:
            return pol_losses

    def save(self, path):
        self.prep_rollout("cpu")
        save_dict = self.policy.get_save_dict()
        save_dict.update(self.lang_learner.get_save_dict())
        if self.comm_policy is not None:
            save_dict.update(self.comm_policy.get_save_dict())
        torch.save(save_dict, path)

    def load(self, path):
        save_dict = torch.load(path, map_location=torch.device('cpu'))
        self.policy.load_params(save_dict["agents_params"])
        self.lang_learner.load_params(save_dict)
        # if self.comm_pol_algo in ["ppo_mlp"]:
        #     self.comm_policy.load_params(save_dict)
