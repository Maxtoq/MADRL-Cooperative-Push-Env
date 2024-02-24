import torch
import numpy as np
import torch.nn as nn

from .utils import huber_loss
from .valuenorm import ValueNorm


class ACC_Trainer:

    def __init__(self, 
            args, agents, lang_learner, buffer, device=torch.device("cpu")):
        self.agents = agents
        self.lang_learner = lang_learner
        self.buffer = buffer
        self.device = device
        self.share_params = args.share_params

        # PPO params
        self.clip_param = args.clip_param
        self.ppo_epoch = args.ppo_epoch
        self.n_mini_batch = args.n_mini_batch
        self.value_loss_coef = args.value_loss_coef
        self.entropy_coef = args.entropy_coef
        self.max_grad_norm = args.max_grad_norm
        self.huber_delta = args.huber_delta

        # Language params
        self.lang_n_epochs = args.lang_n_epochs
        self.temp = args.lang_temp

        self.clip_loss = nn.CrossEntropyLoss()
        self.captioning_loss = nn.NLLLoss()

        self.act_value_normalizer = ValueNorm(1).to(device)
        self.comm_value_normalizer = ValueNorm(1).to(device)

    def _compute_advantages(self):
         # Compute and normalize action advantages
        act_advantages = self.buffer.act_returns[:-1] - self.act_value_normalizer.denormalize(
            self.buffer.act_value_preds[:-1])
        act_advantages_copy = act_advantages.copy()
        mean_act_advantages = np.nanmean(act_advantages_copy)
        std_act_advantages = np.nanstd(act_advantages_copy)
        act_advantages = (act_advantages - mean_act_advantages) / (std_act_advantages + 1e-5)
         # Compute and normalize communication advantages
        comm_advantages = self.buffer.comm_returns[:-1] - self.comm_value_normalizer.denormalize(
            self.buffer.comm_value_preds[:-1])
        comm_advantages_copy = comm_advantages.copy()
        mean_comm_advantages = np.nanmean(comm_advantages_copy)
        std_comm_advantages = np.nanstd(comm_advantages_copy)
        comm_advantages = (comm_advantages - mean_comm_advantages) / (std_comm_advantages + 1e-5)
        return act_advantages, comm_advantages

    def _compute_policy_loss(self, 
            action_log_probs, old_action_log_probs_batch, adv_targ, dist_entropy):
        imp_weights = torch.exp(action_log_probs - old_action_log_probs_batch)

        surr1 = imp_weights * adv_targ
        surr2 = torch.clamp(
            imp_weights, 
            1.0 - self.clip_param, 
            1.0 + self.clip_param) * adv_targ

        loss = -torch.sum(
            torch.min(surr1, surr2), dim=-1, keepdim=True).mean()
        
        loss = loss - dist_entropy * self.entropy_coef

        return loss

    def _compute_value_loss(self, 
            values, value_preds_batch, return_batch, value_norm):
        """
        Calculate value function loss.
        :param values: (torch.Tensor) value function predictions.
        :param value_preds_batch: (torch.Tensor) "old" value  predictions from
            data batch (used for value clip loss)
        :param return_batch: (torch.Tensor) reward to go returns.
        :param value_norm: (ValueNorm) value normalizer instance.

        :return value_loss: (torch.Tensor) value function loss.
        """
        value_pred_clipped = value_preds_batch + \
            (values - value_preds_batch).clamp(-self.clip_param, self.clip_param)
        value_norm.update(return_batch)
        error_clipped = value_norm.normalize(return_batch) - value_pred_clipped
        error_original = value_norm.normalize(return_batch) - values

        value_loss_clipped = huber_loss(error_clipped, self.huber_delta)
        value_loss_original = huber_loss(error_original, self.huber_delta)

        value_loss = torch.max(value_loss_original, value_loss_clipped)
        
        value_loss = value_loss.mean()

        return value_loss

    def _train_mappo(self, agent, sample, train_comm_head):
        policy_input_batch, critic_input_batch, rnn_states_batch, \
            critic_rnn_states_batch, env_actions_batch, comm_actions_batch, \
            old_env_action_log_probs_batch, old_comm_action_log_probs_batch, \
            act_value_preds_batch, comm_value_preds_batch, act_returns_batch, \
            comm_returns_batch, masks_batch, act_advt_batch, comm_advt_batch, \
            envs_train_comm = sample

        policy_input_batch = torch.from_numpy(policy_input_batch).to(self.device)
        critic_input_batch = torch.from_numpy(critic_input_batch).to(self.device)
        rnn_states_batch = torch.from_numpy(rnn_states_batch).to(self.device)
        critic_rnn_states_batch = torch.from_numpy(critic_rnn_states_batch).to(
            self.device)
        env_actions_batch = torch.from_numpy(env_actions_batch).to(self.device)
        comm_actions_batch = torch.from_numpy(comm_actions_batch).to(self.device)
        act_value_preds_batch = torch.from_numpy(
            act_value_preds_batch).to(self.device)
        comm_value_preds_batch = torch.from_numpy(
            comm_value_preds_batch).to(self.device)
        act_returns_batch = torch.from_numpy(act_returns_batch).to(self.device)
        comm_returns_batch = torch.from_numpy(comm_returns_batch).to(self.device)
        masks_batch = torch.from_numpy(masks_batch).to(self.device)
        old_env_action_log_probs_batch = torch.from_numpy(
            old_env_action_log_probs_batch).to(self.device)
        old_comm_action_log_probs_batch = torch.from_numpy(
            old_comm_action_log_probs_batch).to(self.device)
        act_advt_batch = torch.from_numpy(act_advt_batch).to(self.device)
        comm_advt_batch = torch.from_numpy(comm_advt_batch).to(self.device)

        # Agent forward pass
        act_values, comm_values, env_action_log_probs, act_dist_entropy, \
            comm_action_log_probs, comm_dist_entropy = agent.evaluate_actions(
                policy_input_batch, critic_input_batch, rnn_states_batch, 
                critic_rnn_states_batch, env_actions_batch, comm_actions_batch, 
                masks_batch, train_comm_head)

        # Actor loss
        actor_loss = self._compute_policy_loss(
            env_action_log_probs, 
            old_env_action_log_probs_batch, 
            act_advt_batch, 
            act_dist_entropy)
        # Act Value loss
        act_value_loss = self._compute_value_loss(
            act_values, 
            act_value_preds_batch, 
            act_returns_batch, 
            self.act_value_normalizer)

        log_losses = {
            "actor_loss": actor_loss.item(),
            "act_value_loss": act_value_loss.item()}

        # Communicator losses
        if train_comm_head:
            # The comm head is trained only on envs that used generated comm
            if envs_train_comm.sum() > 0:
                comm_loss = self._compute_policy_loss(
                    comm_action_log_probs[envs_train_comm], 
                    old_comm_action_log_probs_batch[envs_train_comm], 
                    comm_advt_batch[envs_train_comm], 
                    comm_dist_entropy)
                log_losses["comm_loss"] = comm_loss.item()
            else:
                comm_loss = torch.zeros_like(actor_loss)

            comm_value_loss = self._compute_value_loss(
                comm_values, 
                comm_value_preds_batch, 
                comm_returns_batch, 
                self.comm_value_normalizer)
            
            log_losses["comm_value_loss"] = comm_value_loss.item()
        else:
            comm_loss = torch.zeros_like(actor_loss)
            comm_value_loss = torch.zeros_like(act_value_loss)

        loss = actor_loss + comm_loss + act_value_loss + comm_value_loss
        
        # Update
        agent.act_comm_optim.zero_grad()
        agent.critic_optim.zero_grad()
        loss.backward()
        agent.act_comm_optim.step()
        agent.critic_optim.step()

        return log_losses

    def _compute_clip_loss(self, obs_contexts, lang_contexts):
        # Compute similarity
        norm_obs_contexts = obs_contexts / obs_contexts.norm(
            dim=1, keepdim=True)
        norm_lang_contexts = lang_contexts / lang_contexts.norm(
            dim=1, keepdim=True)
        sim = norm_obs_contexts @ norm_lang_contexts.t() * self.temp
        mean_sim = sim.diag().mean()

        # Compute CLIP loss
        labels = torch.arange(obs_contexts.shape[0]).to(self.device)
        loss_o = self.clip_loss(sim, labels)
        loss_l = self.clip_loss(sim.t(), labels)
        clip_loss = (loss_o + loss_l) / 2

        return clip_loss, mean_sim.item()

    # def _train_clip(self, sample):
    #     obs_batch, parsed_obs_batch, n_mini_batch = sample 
    #     print(obs_batch.shape, len(parsed_obs_batch), n_mini_batch)

    #     # Encode observations
    #     obs_contexts = self.lang_learner.obs_encoder(
    #         torch.from_numpy(obs_batch).to(self.device))
    #     # Encode sentences
    #     lang_contexts = self.lang_learner.lang_encoder(parsed_obs_batch)
    #     lang_contexts = lang_contexts.squeeze()

    #     # Compute CLIP loss per mini-batch
    #     tot_clip_loss = []
    #     tot_mean_sim = []
    #     for b_i in range(n_mini_batch):
    #         obs_context_batch = obs_contexts[
    #             b_i * self.clip_batch_size:(b_i + 1) * self.clip_batch_size]
    #         lang_context_batch = lang_contexts[
    #             b_i * self.clip_batch_size:(b_i + 1) * self.clip_batch_size]
            
    #         print(obs_context_batch.shape, lang_context_batch.shape)
    #         # CLIP loss
    #         clip_loss, mean_sim = self._compute_clip_loss(
    #             obs_context_batch, lang_context_batch)

    #         tot_clip_loss.append(clip_loss)
    #         tot_mean_sim.append(mean_sim)
    #     exit()

    #     clip_loss = sum(tot_clip_loss)

    #     # Update
    #     self.lang_learner.clip_optim.zero_grad()
    #     clip_loss.backward()
    #     self.lang_learner.clip_optim.step()

    #     clip_loss = clip_loss / (n_mini_batch * self.clip_batch_size)
    #     mean_sim = sum(tot_mean_sim) / n_mini_batch
        
    #     return clip_loss, mean_sim

    def _compute_capt_loss(self, preds, targets):
        dec_loss = 0
        for d_o, e_t in zip(preds, targets):
            e_t = torch.argmax(e_t, dim=1).to(self.device)
            dec_loss += self.captioning_loss(d_o[:e_t.size(0)], e_t)
        return dec_loss

    # def _train_capt(self, agent, sample):
    #     policy_input_batch, masks_batch, rnn_states_batch, parsed_obs_batch \
    #         = sample

    #     policy_input_batch = torch.from_numpy(policy_input_batch).to(self.device)
    #     masks_batch = torch.from_numpy(masks_batch).to(self.device)
    #     rnn_states_batch = torch.from_numpy(rnn_states_batch).to(self.device)

    #     # Pass through acc
    #     comm_actions = agent.get_comm_actions(
    #         policy_input_batch, rnn_states_batch, masks_batch)

    #     # Decode
    #     encoded_targets = self.lang_learner.word_encoder.encode_batch(
    #         parsed_obs_batch)
    #     decoder_outputs, _ = self.lang_learner.decoder(
    #         comm_actions, encoded_targets)

    #     # Captioning loss
    #     capt_loss = self._compute_capt_loss(decoder_outputs, encoded_targets)

    #     # Update
    #     agent.capt_optim.zero_grad()
    #     capt_loss.backward()
    #     agent.capt_optim.step()

    #     return capt_loss.item() / policy_input_batch.shape[0]

    def _train_language(self, agent, sample):
        policy_input_batch, masks_batch, rnn_states_batch, parsed_obs_batch \
            = sample

        policy_input_batch = torch.from_numpy(policy_input_batch).to(self.device)
        masks_batch = torch.from_numpy(masks_batch).to(self.device)
        rnn_states_batch = torch.from_numpy(rnn_states_batch).to(self.device)

        # Pass through acc
        comm_actions = agent.get_comm_actions(
            policy_input_batch, rnn_states_batch, masks_batch)

        # CLIP
        # Encode sentences
        lang_contexts = self.lang_learner.lang_encoder(parsed_obs_batch)
        lang_contexts = lang_contexts.squeeze()

        # CLIP loss
        # clip_loss, mean_sim = self._compute_clip_loss(
        #     comm_actions, lang_contexts)
        # Compute CLIP loss per mini-batch
        n_mini_batch = 2
        mini_batch_size = 256
        ids = np.random.choice(
            comm_actions.shape[0], 
            size=mini_batch_size * n_mini_batch, 
            replace=False).reshape((n_mini_batch, mini_batch_size))
        tot_clip_loss = []
        tot_mean_sim = []
        for b_i in range(n_mini_batch):
            comm_action_batch = comm_actions[ids[b_i]]
            lang_context_batch = lang_contexts[ids[b_i]]
            
            # CLIP loss
            clip_loss, mean_sim = self._compute_clip_loss(
                comm_action_batch, lang_context_batch)

            tot_clip_loss.append(clip_loss)
            tot_mean_sim.append(mean_sim)
        clip_loss = sum(tot_clip_loss)

        # Captioning
        # Decode
        encoded_targets = self.lang_learner.word_encoder.encode_batch(
            parsed_obs_batch)
        decoder_outputs, _ = self.lang_learner.decoder(
            comm_actions, encoded_targets)
        # Captioning loss
        capt_loss = self._compute_capt_loss(decoder_outputs, encoded_targets)
        
        # Update
        agent.lang_optim.zero_grad()
        tot_loss = clip_loss + capt_loss
        tot_loss.backward()
        agent.lang_optim.step()

        capt_loss = capt_loss.item() / policy_input_batch.shape[0]
        clip_loss = clip_loss.item() / n_mini_batch
        mean_sim = sum(tot_mean_sim) / n_mini_batch

        return capt_loss, clip_loss, mean_sim


    def train(self, 
            warmup=False, train_comm_head=True, train_lang=True, 
            envs_train_comm=None):
        """
        Train LGMARL.

        :param train_comm_head: (bool) Whether to train the communicator head.
        :param train_lang: (bool) Whether to train language modules.
        :param envs_train_comm: (nd.ndarray) Booleans indicating which 
            environment must be used for training the communication head.

        :return losses: (dict) Contains losses obtained during update.
        """
        for a in self.agents:
            a.warmup_lr(warmup)
            
        act_advantages, comm_advantages = self._compute_advantages()
        
        losses = {
            "act_value_loss": 0.0,
            "actor_loss": 0.0}
        if train_comm_head:
            losses["comm_value_loss"] = 0.0
            losses["comm_loss"] = 0.0

        # Train policy
        num_updates = self.ppo_epoch * self.n_mini_batch
        for _ in range(self.ppo_epoch):
            data_generator = self.buffer.recurrent_policy_generator(
                act_advantages, comm_advantages, envs_train_comm)
    
            for sample in data_generator:
                if self.share_params:
                    loss = self._train_mappo(
                        self.agents[0], sample, train_comm_head)
                    
                    for key in loss:
                        losses[key] += loss[key] / num_updates
                else:
                    for a_i in range(len(self.agents)):
                        sample_i = tuple(
                            [batch[:, a_i] for batch in sample])

                        loss = self._train_mappo(
                            self.agents[a_i], sample_i, train_comm_head)
                        
                        for key in loss:
                            losses[key] += loss[key] / (
                                num_updates * len(self.agents))

        # Train language
        if train_lang:
            # Train CLIP
            # sample = self.buffer.sample_clip()
            # clip_loss, mean_sim = self._train_clip(sample)

            # Train captioning
            clip_loss = 0.0
            dec_loss = 0.0
            mean_sim = 0.0
            for i in range(self.lang_n_epochs):
                sample = self.buffer.sample_lang()
                if self.share_params:
                    # dec_loss += self._train_capt(self.agents[0], sample)
                    dl, cl, ms = self._train_language(self.agents[0], sample)

                    dec_loss += dl / self.lang_n_epochs
                    clip_loss += cl / self.lang_n_epochs
                    mean_sim += ms / self.lang_n_epochs
                else:
                    for a_i in range(len(self.agents)):
                        sample_i = (
                            *[batch[:, a_i] for batch in sample[:-1]],
                            sample[-1][a_i])

                        dl, cl, ms = self._train_language(
                            self.agents[a_i], sample_i)

                        dec_loss += dl / (self.lang_n_epochs * len(self.agents))
                        clip_loss += cl / (self.lang_n_epochs * len(self.agents))
                        mean_sim += ms / (self.lang_n_epochs * len(self.agents))


            losses["clip_loss"] = clip_loss
            losses["dec_loss"] = dec_loss
            losses["mean_sim"] = mean_sim

        return losses