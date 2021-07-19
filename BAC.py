# -*- coding: utf-8 -*-
"""
Created on Fri Jun 25 18:58:44 2021

@author: DELL
"""

import numpy as np
import math
from scipy.sparse import csr_matrix, linalg
import pandas as pd


class BAC_main:
    
    def __init__(self, gym_env, domain, learning_params):
        self.gym_env = gym_env
        self.domain = domain
        self.learning_params = learning_params
        self.data = np.zeros((self.learning_params.num_update_max, 6))
        self.grad_store = []
        self.policy_store = []
        
    #Bayesian Actor-Critic function
    def BAC(self):
        d = self.domain
        learning_params = self.learning_params
        num_output = (learning_params.num_update_max / learning_params.sample_interval)
        perf = np.zeros((math.ceil(num_output), 3))
        
        Pandas_dataframe = pd.DataFrame(np.zeros((learning_params.num_update_max, 6)))
        Pandas_dataframe = Pandas_dataframe.astype('object')
        
        STEP = 1
        
        for i in range(0, learning_params.num_trial):
            
           # exptime = now#Add current time module
            #toc
            
            #Add file handling protocol
            theta = np.zeros((d.num_policy_param, 1))
            
            #Fix the following expression
            alpha_schedule = learning_params.alp_init_BAC * (learning_params.alp_update_param / 
                                                                 (learning_params.alp_update_param + 
                                                                  (np.arange(1,(learning_params.num_update_max + 1)) - 1)))
            
            for j in range(0, learning_params.num_update_max + 1):
                
                reward1 = 0
                reward2 = 0
                # Policy evaluation after every n(sample_interval) policy updates
                if (j % (learning_params.sample_interval)) == 0:
                    evalpoint = math.floor(j / learning_params.sample_interval)
                    perf[evalpoint, 0], perf[evalpoint, 1], perf[evalpoint, 2] = d.perf_eval(theta, d, learning_params)
                    # perf_eval() returns perf, reward1, reward2
                    
                G = csr_matrix((d.num_policy_param, d.num_policy_param), dtype = np.float32)
                
                # Run num_episode episodes for BAC Gradient evaluation
                # Gradient evaluation occurs in batches of episodes (e.g. 5)
                for l in range(1, learning_params.num_episode+1):
                    t = 0
                    episode_states = []
                    episode_scores = []
                    
                    env_current_state = self.gym_env.reset()#state = d.random_state(d)
                    state = d.c_map_eval(env_current_state)
                    done = False
                    
                    # The problem now is handling of state in calc_score.
                    # calc_score uses y array which is essentially a C map of
                    # state = (position, velocity)
                    # C maps are exclusive of each environment and observations
                    a, scr = d.calc_score(theta, state)
                    scr = csr_matrix(scr)
                    # print(scr)
                    
                    #state is a "list" object with x, y and isgoal elements
                    while done == False or t < learning_params.episode_len_max:
                        
                        for istep in range(0, STEP):
                            if done == 0:
                                # state, _ = d.dynamics(state, a, d)
                                # state = d.is_goal(state, d)
                                state[0], reward, done, _ = self.gym_env.step(np.array([a]))
                                state = d.c_map_eval(state[0])
                                state.append(done)
                                reward1 += reward1
                                reward2 -= 1
                        
                        # G is a N x N matrix. We do outer product of scr
                        # scr is a row-wise 2D array of shape = (32, 1)
                        G = G + (scr @ csr_matrix.transpose(scr)) ## Use @ for dot multiplication...
                                                          ## of sparse matrices
                        
                        episode_states.append(state)
                        episode_scores.append(scr)
                        
                        a, scr = d.calc_score(theta, state)
                        
                        scr = csr_matrix(scr)
                        
                        t = t + 1
                    
                    # Create the batch data of num_episode episodes
                    # to be given for gradient estimation
                    episodes = (episode_states, episode_scores, t)
                
                #Fix the identity matrix
                G = G + 1e-6 * np.identity(G.shape[0])
                grad_BAC = self.BAC_grad(episodes, G, d, learning_params)
                
                if learning_params.alp_schedule:
                    alp = alpha_schedule[j]
                else:
                    alp = learning_params.alp_init_BAC
                
                theta = theta + (alp * grad_BAC)
                error = state[0][0][0] - self.gym_env.observation_space.high[0]
                mae = abs(error)/(j+1)
                mse = math.pow(error, 2)/(j+1)
                # Data storing in self.data
                self.data[j] = np.array([j+1, mae, mse, alp, reward1, reward2])
                self.grad_store.append(grad_BAC)
                self.policy_store.append(theta)
                
            Pandas_dataframe = pd.DataFrame({"Episode Batch":self.data[:, 0],
                                     "Learning Rate":self.data[:, 3], "Mean Absolute Error":self.data[:, 1],
                                     "Mean Squared Error":self.data[:, 2], "Batch Gym Reward":self.data[:, 4],
                                     "Batch User Reward":self.data[:, 5], "BAC Gradient":self.grad_store,
                                     "Policy Evolution":self.policy_store})
            perf_dataframe = pd.DataFrame({"BAC Evaluation Batch":perf[:,0], "Gym Batch Reward":perf[:,1],
                                           "User Defined Batch Reward":perf[:,2]})
        return perf_dataframe, theta, Pandas_dataframe
    
    #Bayesian Actor=Critic Gradient Function
    def BAC_grad(self, episodes, G, domain_params, learning_params):
        gam = learning_params.gam
        gam2 = gam**2
        
        nu = 0.1
        sig = 3
        sig2 = sig**2
        ck_xa = 1
        sigk_x = 1.3 * 0.25
        
        #Initialization
        T = 0
        m = 0
        statedic = []
        scr_dic = []
        invG_scr_dic = []
        alpha = []
        C = []
        Kinv = []
        k = []
        c = []
        z = []
        
        for l in range(1, learning_params.num_episode):
            ISGOAL = 0
            t = 0
            T = T + 1
            c = np.zeros((m, 1))
            d = 0
            s = math.inf
            # state and scr are lists appended as a 1-D column-wise array objects.
            state = episodes[0][t]
            scr = episodes[1][t]
            scrT = csr_matrix.transpose(scr)
            
            temp1 = domain_params.kernel_kxx(state, domain_params)
            invG_scr = linalg.spsolve(G, scr)
            
            temp2 = ck_xa * (scrT @ invG_scr)
            kk = temp1 + temp2
            
            if m > 0:
                k = ck_xa * (scrT @ invG_scr_dic) #State-action kernel -- Fisher Information Kernel
                k = k + domain_params.kernel_kx(state, statedic, domain_params)
                kT = np.row_stack(k)
                
                a = np.matmul(Kinv, kT)
                delta = kk - np.matmul(k, a)
            else:
                k = []
                a = []
                delta = kk
            # delta cocmes out to be a 1x1 array which must be changed to scalar
            # hence we use delta[0] and kk[0]
            if m == 0 or delta[0] > nu:
                a_hat = a
                a_hatT = np.transpose(a_hat)
                #Treat all of them as array 'list'
                h = np.row_stack((a, -gam)) # h = [[a], [-gam]]
                a = np.row_stack((z, 1)) # a = [[z], [1]]
                alpha = np.row_stack((alpha, 0)) # alpha = [[alpha], [0]]
                C = np.row_stack((np.append(C, z), np.append(np.transpose(z), 0))) 
                # [[C, z], [np.transpose(z), 0]]
                
                Kinv = (1 / delta[0]) * [[(delta[0] * Kinv) + (a_hat * a_hatT), (-1 * a_hat)],
                        [(-1*a_hatT) , 1]]
                print(Kinv)
                z = np.row_stack((z, 0)) # [[z], [0]]
                c = np.row_stack((c, 0)) # [[c], [0]]
                statedic.append(state)
                scr_dic.append(scr)
                invG_scr_dic.append(invG_scr)
                m = m + 1
                k = np.append(kT, kk, axis = 0)
        
            #Time-loop
            while (t < episodes[2]):
                state_old = state
                k_old = k
                kk_old = kk
                a_old = a
                c_old = c
                s_old = s
                d_old = d
                
                r = domain_params.calc_reward(state_old, -1, domain_params)
                
                coef = (gam * sig2) / s_old
                
                #Goal update
                if ISGOAL == 1:
                    dk = k_old
                    dkT = np.transpose(dk)
                    dkk = kk_old
                    h = a_old
                    c = (coef * c_old) + h - (C * dk)
                    s = sig2 - (gam * sig2 * coef) + (dkT * (c + (coef * c_old)))
                    d = (coef * d_old) + r - (dkT * alpha)
                
                #Non-goal update    
                else:
                    state = episodes[0][t + 1]
                    scr = episodes[1][t + 1]
                    scrT = csr_matrix.transpose(scr)
                    
                    if state[2] == True:
                        ISGOAL = 1
                        t = t-1
                        T = T-1
                    
                    temp1 = domain_params.kernel_kxx(state, domain_params)
                    invG_scr = linalg.spsolve(G, scr)
                    temp2 = ck_xa * (scrT @ invG_scr)
                    kk = temp1 + temp2
                    
                    k = ck_xa * (scrT @ invG_scr_dic)
                    k = k + domain_params.kernel_kx(state, statedic, domain_params)
                    
                    a = Kinv * k
                    delta[0] = kk - (np.transpose(k) * a)
                    
                    dk = k_old - (gam * k)
                    d = (coef * d_old) + r - (np.transpose(dk) * alpha)
                    
                    if delta[0] > nu:
                        h = [a_old, -gam]
                        dkk = (np.transpose(a_old) * (k_old - (2 * gam * k))) + (gam2 * kk)
                        c = (coef * [c_old, 0]) + h - [C * dk, 0]
                        s = ((1 + gam2) * sig2) + dkk - (np.transpose(dk) * C * dk) + (2 * coef * np.transpose(c_old) * dk) - (gam * sig2 * coef)
                        alpha = [alpha, 0]
                        C = np.row_stack((np.append(C, z), np.append(np.transpose(z), 0)))
                        statedic.append(state)
                        scr_dic.append(scr)
                        invG_scr_dic.append(invG_scr)
                        
                        m = m + 1
                        Kinv = np.multiply([[(delta[0] * Kinv) + (a * np.transpose(a)), -1 * a],
                                [np.transpose(-1 * a)                      , 1]], 1/delta[0])
                        a = [[z], [1]]
                        z = [[z], [0]]
                        k = [[k], [kk]]
                        
                    else:#delta <= nu
                        h = a_old - (gam * a)
                        dkk = np.transpose(h) * dk
                        c = (coef * c_old) + h - (C * dk)
                        s = ((1-gam2) * sig2) + (np.transpose(dk) * (c + (coef * c_old))) - (
                            gam * sig2 * coef)
                
                #Alpha update
                alpha = alpha + (c * (d / s))
                #C update
                C = C + (c * (np.transpose(c) / s))
                
                #Update time counters
                t = t + 1
                T = T + 1
        
        #For all the fuss we went through, FINALLY!
        grad = ck_xa * (scr_dic * alpha)
        
        return grad
                            
                    
                        
                    
        