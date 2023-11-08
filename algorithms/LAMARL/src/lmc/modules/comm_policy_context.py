import copy
import torch
import random
import itertools
import numpy as np

from torch import nn
from gym import spaces

from src.lmc.modules.networks import MLPNetwork, init
from src.lmc.policy.mappo.mappo_shared import MAPPO
from src.lmc.utils import get_mappo_args


def torch2numpy(x):
    return x.detach().cpu().numpy()


# class TextActorCritic(nn.Module):
    
#     def __init__(self, word_encoder, pretrained_decoder, context_dim, 
#             max_sent_len, device, train_topk=1):
#         super(TextActorCritic, self).__init__()
#         self.word_encoder = word_encoder
#         self.max_sent_len = max_sent_len
#         self.device = device
#         # TODO add topk param handle
#         self.train_topk = train_topk
#         # RNN encoder
#         self.gru = copy.deepcopy(pretrained_decoder.gru)
#         # Policy and value heads
#         self.actor = copy.deepcopy(pretrained_decoder.out)
#         self.critic = init(nn.Linear(context_dim, 1), gain=0.01)
            
#     def gen_messages(self, context_batch):
#         """
#         :param context_batch (torch.Tensor): Batch of context vectors,
#                 dim=(1, batch_size, context_dim).
#         """
#         batch_size = context_batch.shape[1]
#         # Set initial hidden states and token
#         hidden = context_batch
#         last_tokens = torch.tensor(
#             np.array([[self.word_encoder.SOS_ENC]])).float().repeat(
#                 1, batch_size, 1).to(self.device)
        
#         batch_tokens = []
#         batch_log_probs = []
#         batch_token_log_probs = []
#         batch_value_preds = []
#         batch_masks = [np.ones(batch_size)]
#         last_topi = torch.zeros(batch_size)
#         # batch_len_sentences = np.zeros(batch_size)
#         sentences = [[] for b_i in range(batch_size)]
#         for t_i in range(self.max_sent_len):
#             # Encode with RNN
#             _, hidden = self.gru(last_tokens, hidden)
            
#             # Get token predictions from actor
#             log_probs = self.actor(hidden)
            
#             # Get values from critic
#             value_preds = self.critic(hidden)
            
#             # Sample next token
#             _, topi = log_probs.topk(1)
#             topi = topi.squeeze()
#             tokens = self.word_encoder.token_encodings[topi.cpu()]
            
#             # Make token_log_prob
#             token_log_probs = log_probs.gather(-1, topi.reshape(1, -1, 1))
            
#             # Make mask: 1 if last token is not EOS and last mask is not 0
#             masks = (
#                 np.where(last_topi.cpu() == self.word_encoder.EOS_ID, 0.0, 1.0) * \
#                 np.where(batch_masks[-1] == 0.0, 0.0, 1.0))
#             last_topi = topi
            
#             # Stop early if all sentences are finished
#             if sum(masks) == 0:
#                 break
            
#             # Add decoded tokens to sentences
#             for b_i in range(batch_size):
#                 if masks[b_i] and topi[b_i] != self.word_encoder.EOS_ID:
#                     sentences[b_i].append(
#                         self.word_encoder.index2token(topi[b_i]))
            
#             batch_tokens.append(tokens)
#             batch_log_probs.append(torch2numpy(log_probs))
#             batch_token_log_probs.append(torch2numpy(token_log_probs))
#             batch_value_preds.append(torch2numpy(value_preds))
#             batch_masks.append(masks)
            
#             last_tokens = torch.Tensor(tokens).unsqueeze(0).to(self.device)
            
#         # Compute last value
#         _, hidden = self.gru(last_tokens, hidden)
#         value_preds = self.critic(hidden)
#         batch_value_preds.append(torch2numpy(value_preds))
        
#         tokens = np.stack(batch_tokens, dtype=np.float32)
#         log_probs = np.concatenate(batch_log_probs)
#         token_log_probs = np.concatenate(batch_token_log_probs)
#         value_preds = np.concatenate(batch_value_preds)
#         masks = np.stack(batch_masks)
        
#         return tokens, token_log_probs, value_preds, masks, sentences, log_probs
    
#     def evaluate_tokens(self, context_batch, token_batch):
#         """
#         Evaluate generated tokens with the current policy and value.
#         :param context_batch (torch.Tensor): Batch of communication contexts
#             (initial hidden state of gru), dim=(1, batch_size, context_dim)
#         :param token_batch (torch.Tensor): Batch of generated tokens, 
#             dim=(seq_len, batch_size, token_dim)
        
#         :return token_log_probs (torch.Tensor): Log-probabilities of given 
#             tokens, dim=(seq_len, batch_size, 1)
#         :return entropy (torch.Tensor): Entropy of the output probabilities, 
#             dim=(1)
#         :return value_preds (torch.Tensor): Value predictions, dim=(seq_len, 
#             batch_size, 1)
#         """
#         # Add SOS token
#         sos_tensor = torch.Tensor(
#             np.array([self.word_encoder.SOS_ENC])).repeat(
#                 1, context_batch.shape[1], 1).to(self.device)
#         input_tokens = torch.cat((sos_tensor, token_batch)).to(self.device)

#         outputs, _ = self.gru(input_tokens, context_batch)
        
#         # Get log_probs and entropy
#         log_probs = self.actor(outputs)
#         token_log_probs = log_probs.gather(
#             -1, token_batch.argmax(-1).unsqueeze(-1))
#         entropy = -(log_probs * torch.exp(log_probs)).mean()

#         # Get values
#         value_preds = self.critic(outputs)

#         return token_log_probs, entropy, value_preds

class CommPol_Context:
    """ 
    Communication module with a recurrent context encoder, 
    a policy that generates sentences and a value that estimates
    the quality of the current state (previous hidden state).
    It is trained using PPO, fine-tuning a pretrained policy.
    """
    def __init__(self, args, n_agents, lang_learner, device="cpu"):
        self.n_agents = n_agents
        self.n_envs = args.n_parallel_envs
        self.lr = args.comm_lr
        self.n_epochs = args.comm_n_epochs
        self.ppo_clip_param = args.comm_ppo_clip_param
        self.entropy_coef = args.comm_entropy_coef
        self.vloss_coef = args.comm_vloss_coef
        self.max_grad_norm = args.comm_max_grad_norm
        self.n_mini_batch = args.comm_n_mini_batch
        self.device = device
        self.warming_up = False
        
        self.lang_learner = lang_learner

        comm_policy_args = get_mappo_args(args)
        context_dim = args.context_dim
        input_dim = context_dim * 2
        low = np.full(context_dim, -np.inf)
        high = np.full(context_dim, np.inf)
        act_space = spaces.Box(low, high)
        self.context_encoder_policy = MAPPO(
            comm_policy_args, 
            n_agents, 
            input_dim, 
            input_dim * n_agents, 
            act_space, 
            device)

        self.values = None
        self.comm_context = None
        self.action_log_probs = None
        self.rnn_states = None
        self.critic_rnn_states = None

    def prep_rollout(self, device=None):
        if device is None:
            device = self.device
        self.context_encoder_policy.prep_rollout(device)

    def prep_training(self):
        self.context_encoder_policy.prep_training()

    def start_episode(self):
        self.context_encoder_policy.start_episode()
        
    @torch.no_grad()
    def get_messages(self, obs, lang_context):
        """
        Perform a communication step: encodes obs and previous messages and
        generates messages for this step.
        :param obs: (np.ndarray) agents' observations for all parallel 
            environments, dim=(n_envs, n_agents, obs_dim)
        :param lang_context: (np.ndarray) Language contexts from last step, 
            dim=(n_envs, n_agents, context_dim)
            
        :return messages (list(list(str))): messages generated for each agent,
            for each parallel environment
        """
        # Encode inputs
        # obs_context = []
        obs = torch.Tensor(obs).view(self.n_envs * self.n_agents, -1)
        obs_context = self.lang_learner.encode_observations(obs)
        obs_context = obs_context.view(self.n_envs, self.n_agents, -1)

        # Repeat lang_contexts for each agent in envs
        lang_context = torch.from_numpy(lang_context.repeat(
            self.n_agents, 0).reshape(
                self.n_envs, self.n_agents, -1)).to(self.device)

        input_context = torch.cat((obs_context, lang_context), dim=-1)
        
        # Make all possible shared inputs
        shared_input = []
        ids = list(range(self.n_agents)) * 2
        for a_i in range(self.n_agents):
            shared_input.append(
                input_context[:, ids[a_i:a_i + self.n_agents]].reshape(
                    self.n_envs, 1, -1))
        shared_input = torch.cat(shared_input, dim=1)

        self.context_encoder_policy.store_obs(
            torch2numpy(input_context), torch2numpy(shared_input))

        self.values, self.comm_context, self.action_log_probs, self.rnn_states, \
            self.critic_rnn_states = self.context_encoder_policy.get_actions()

        messages = self.lang_learner.generate_sentences(torch.Tensor(
            self.comm_context).view(self.n_envs * self.n_agents, -1).to(
                self.device))
        
        return messages

    # def _rand_filter_messages(self, messages):
    #     """
    #     Randomly filter out perfect messages.
    #     :param messages (list(list(list(str)))): Perfect messages, ordered by
    #         environment, by agent.

    #     :return filtered_broadcast (list(list(str))): Filtered message to 
    #         broadcast, one for each environment.
    #     """
    #     filtered_broadcast = []
    #     for env_messages in messages:
    #         env_broadcast = []
    #         for message in env_messages:
    #             if random.random() < 0.2:
    #                 env_broadcast.extend(message)
    #         filtered_broadcast.append(env_broadcast)
    #     return filtered_broadcast
    
    @torch.no_grad()
    def comm_step(self, obs, lang_contexts, perfect_messages=None):
        # Get messages
        messages = self.get_messages(obs, lang_contexts)
        
        # Arrange messages by env
        broadcasts = []
        messages_by_env = []
        for e_i in range(self.n_envs):
            env_broadcast = []
            for a_i in range(self.n_agents):
                env_broadcast.extend(messages[e_i * self.n_agents + a_i])
            broadcasts.append(env_broadcast)
            messages_by_env.append(messages[
                e_i * self.n_agents:e_i * self.n_agents + self.n_agents])

        new_lang_contexts = self.lang_learner.encode_sentences(
            broadcasts).cpu().numpy()

        # # TEST with perfect messages
        # broadcasts = self._rand_filter_messages(perfect_messages)
        # new_lang_contexts = self.lang_learner.encode_sentences(broadcasts).detach().cpu().numpy()
        
        # Return messages and lang_context
        return broadcasts, messages_by_env, new_lang_contexts
    
    def store_rewards(self, message_rewards, dones):
        """
        Send rewards for each sentences to the buffer to compute returns.
        :param message_rewards (np.ndarray): Rewards for each generated 
            sentence, dim=(n_envs, n_agents).
        :param dones (np.ndarray): Done state of each environment, 
            dim=(n_envs, n_agents).

        :return rewards (dict): Rewards to log.
        """
        self.context_encoder_policy.store_act(
            message_rewards, dones, 
            self.values, 
            self.comm_context, 
            self.action_log_probs, 
            self.rnn_states, 
            self.critic_rnn_states)

        rewards = {
            "message_reward": message_rewards.mean()
        }

        return rewards
    
    def train(self, warmup=False):
        losses = self.context_encoder_policy.train(warmup)
        return losses

    def get_save_dict(self):
        save_dict = {
            "context_encoder": self.context_encoder_policy.get_save_dict()}
            # "comm_policy": self.comm_policy.state_dict(),
            # "comm_optim": self.optim.state_dict()}
        return save_dict

    def load_params(self, save_dict):
        self.lang_learner.load_params(save_dict)
        # if "context_encoder" in save_dict:
        #     self.context_encoder.load_state_dict(save_dict["context_encoder"])
        #     self.comm_policy.load_state_dict(save_dict["comm_policy"])
        #     self.optim.load_state_dict(save_dict["comm_optim"])
        # else: # Starting fine-tuning from pretrained language learner
        #     self.comm_policy.gru.load_state_dict(
        #         self.lang_learner.decoder.gru.state_dict())
        #     self.comm_policy.actor.load_state_dict(
        #         self.lang_learner.decoder.out.state_dict())
