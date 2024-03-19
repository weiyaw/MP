import numpy as np
import jax.numpy as jnp
from jax import grad, jit, vmap,jacfwd,jacrev,random,remat,value_and_grad
from jax.scipy.special import ndtri,erfc,logsumexp,betainc
from jax.scipy.stats import norm,t
from jax.lax import fori_loop,scan
from functools import partial

from .utils.bivariate_copula import norm_copula_logdistribution_logdensity

### Utility functions ###

#Initialize marginal p_0
def init_marginals_single(y_test):
    d = jnp.shape(y_test)[0]

    #initialize
    logcdf_init_marginals = jnp.zeros(d)
    logpdf_init_marginals = jnp.zeros(d)

    logcdf_init_conditionals = jnp.zeros(d)
    logpdf_init_joints = jnp.ones(d)

    ##CONTINUOUS CASE
    #normal(0,1)
    mean0 = 0.
    std0 = 1.

    logcdf_init_marginals = norm.logcdf(y_test,loc = mean0,scale = std0)#marginal initial cdfs
    logpdf_init_marginals= norm.logpdf(y_test,loc = mean0,scale = std0) #marginal initial pdfs

    #clip outliers
    eps = 1e-6
    logcdf_init_marginals = jnp.clip(logcdf_init_marginals,jnp.log(eps),jnp.log(1-eps))
    logpdf_init_marginals =jnp.clip(logpdf_init_marginals, jnp.log(eps),jnp.inf)
    ##
    
    #Joint/conditional from marginals
    logpdf_init_joints= jnp.cumsum(logpdf_init_marginals)
    logcdf_init_conditionals= logcdf_init_marginals

    return  logcdf_init_conditionals,logpdf_init_joints
init_marginals = jit(vmap(init_marginals_single,(0)))

#Compute copula update for a single data point
def update_copula_single(logcdf_conditionals,logpdf_joints,u,v,logalpha,rho): 
    d = jnp.shape(logpdf_joints)[0]

    logcop_distribution,logcop_dens = norm_copula_logdistribution_logdensity(u,v,rho)

    #Calculate product copulas
    logcop_dens_prod = jnp.cumsum(logcop_dens)

    #staggered 1 step to calculate conditional cdfs
    logcop_dens_prod_staggered = jnp.concatenate((jnp.zeros(1),logcop_dens_prod[0:d-1]))

    log1alpha = jnp.log1p(-jnp.exp(logalpha))

    logcdf_conditionals = jnp.logaddexp((log1alpha + logcdf_conditionals),(logalpha + logcop_dens_prod_staggered + logcop_distribution))\
                           -jnp.logaddexp(log1alpha,(logalpha+logcop_dens_prod_staggered))

    logpdf_joints = jnp.logaddexp(log1alpha, (logalpha+logcop_dens_prod))+logpdf_joints     

    return logcdf_conditionals,logpdf_joints

update_copula = jit(vmap(update_copula_single,(0,0,0,None,None,None))) 
### ###

### Functions to calculate overhead v_{1:n} ###

# Compute v_i for a single datum 
@jit
def update_pn(carry,i):
    vn,logcdf_conditionals_yn,logpdf_joints_yn,preq_loglik,rho = carry
    n = jnp.shape(logcdf_conditionals_yn)[0]
    d = jnp.shape(logcdf_conditionals_yn)[1]

    logalpha = jnp.log(2.- (1/(i+1))) - jnp.log(i+2)

    u = jnp.exp(logcdf_conditionals_yn)
    v = jnp.exp(logcdf_conditionals_yn[i])

    vn = vn.at[i].set(v) #remember history of vn
 
    preq_loglik = preq_loglik.at[i].set(logpdf_joints_yn[i,-2:])

    logcdf_conditionals_yn,logpdf_joints_yn= update_copula(logcdf_conditionals_yn,logpdf_joints_yn,u,v,logalpha,rho)

    carry = vn,logcdf_conditionals_yn,logpdf_joints_yn,preq_loglik,rho
    return carry,i

#Scan over y_{1:n}
@jit
def update_pn_scan(carry,rng):
    return scan(update_pn,carry,rng)

#Compute v_{1:n}
@jit
def update_pn_loop(rho,y):
    n = jnp.shape(y)[0]
    d = jnp.shape(y)[1]

    preq_loglik = jnp.zeros((n,2)) #prequential joint loglik for each d,d-1 (density estimation and regression)
    vn = jnp.zeros((n,d)) #conditional cdf history of xn, no need to differentiate wrt

    #initialize cdf/pdf
    logcdf_conditionals_yn, logpdf_joints_yn= init_marginals(y)

    carry = vn,logcdf_conditionals_yn,logpdf_joints_yn,preq_loglik,rho
    rng = jnp.arange(n)
    carry,rng = update_pn_scan(carry,rng)

    vn,logcdf_conditionals_yn,logpdf_joints_yn,preq_loglik,*_ = carry

    return vn,logcdf_conditionals_yn,logpdf_joints_yn,preq_loglik
update_pn_loop_perm = jit(vmap(update_pn_loop,(None,0)))
### ###

### Functions for optimizing prequential log likelihood ###

#Compute permutation-averaged preq loglik
@jit
def negpreq_jointloglik_perm(hyperparam,y_perm):
    rho = 1/(1+jnp.exp(hyperparam)) #force 0 <rho<1

    n = jnp.shape(y_perm)[1]
    d = jnp.shape(y_perm)[2]

    #Compute v_{1:n} and prequential loglik
    vn,logcdf_conditionals_yn,logpdf_joints_yn,preq_loglik = update_pn_loop_perm(rho,y_perm)

    #Average over permutations
    preq_loglik = jnp.mean(preq_loglik,axis = 0)

    #Sum prequential terms
    preq_jointloglik = jnp.sum(preq_loglik[:,-1]) #only look at joint pdf
    return -preq_jointloglik/n
     
#Compute derivatives wrt hyperparameters
grad_jll_perm = jit(grad(negpreq_jointloglik_perm))
fun_grad_jll_perm = jit(value_and_grad(negpreq_jointloglik_perm))

####
#Functions for scipy (convert to numpy array)
def fun_jll_perm_sp(hyperparam,z):
    return np.array(negpreq_jointloglik_perm(hyperparam,z))
def grad_jll_perm_sp(hyperparam,z):
    return np.array(grad_jll_perm(hyperparam,z)) ####

def fun_grad_jll_perm_sp(hyperparam,z):
    value,grad = fun_grad_jll_perm(hyperparam,z)
    return (np.array(value),np.array(grad))
### ###



### Functions for computing p(y) on test points ###

#Update p(y) for a single test point and observed datum
@jit
def update_ptest_single(carry,i):
    vn,logcdf_conditionals_ytest,logpdf_joints_ytest,rho = carry

    logalpha = jnp.log(2.- (1/(i+1))) - jnp.log(i+2)

    u = jnp.exp(logcdf_conditionals_ytest)
    v = vn[i]

    logcdf_conditionals_ytest,logpdf_joints_ytest= update_copula_single(logcdf_conditionals_ytest,logpdf_joints_ytest,u,v,logalpha,rho)

    carry = vn,logcdf_conditionals_ytest,logpdf_joints_ytest,rho
    return carry,i

#Scan over n observed data
@jit
def update_ptest_single_scan(carry,rng):
    return scan(update_ptest_single,carry,rng)

#Compute p(y) for a single test point and y_{1:n}
@jit
def update_ptest_single_loop(vn,rho,y_test):
    n = jnp.shape(vn)[0]

    logcdf_conditionals_ytest, logpdf_joints_ytest= init_marginals_single(y_test)

    carry = vn,logcdf_conditionals_ytest,logpdf_joints_ytest,rho
    rng = jnp.arange(n)
    carry,rng = update_ptest_single_scan(carry,rng)
    vn,logcdf_conditionals_ytest,logpdf_joints_ytest,rho = carry

    return logcdf_conditionals_ytest,logpdf_joints_ytest

update_ptest_single_loop_perm = jit(vmap(update_ptest_single_loop,(0,None,None))) #vmap over vn_perm

#Average p(y) over permutations for single test point
@jit
def update_ptest_single_loop_perm_av(vn_perm,rho,y_test):
    n_perm = jnp.shape(vn_perm)[0]
    logcdf_conditionals, logpdf_joints = update_ptest_single_loop_perm(vn_perm,rho,y_test)
    logcdf_conditionals = logsumexp(logcdf_conditionals,axis = 0) - jnp.log(n_perm)
    logpdf_joints = logsumexp(logpdf_joints,axis = 0) - jnp.log(n_perm)
    return logcdf_conditionals,logpdf_joints

#Vmap over multiple test points
update_ptest_loop_perm_av = jit(vmap(update_ptest_single_loop_perm_av,(None,None,0)))
### ###


