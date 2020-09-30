import tensorflow as tf
import numpy as np

def reconstruction_loss(X, x, x_raw, W, output_activation, D, I, eps=1e-10):
    # reconstruction loss: E[log p(x|z)]
    # xentropy = tf.nn.sigmoid_cross_entropy_with_logits(labels=tf.clip_by_value(X, eps, 1-eps), logits=x_raw)
    # # summing across both dimensions: should I prove this?
    # rec_loss = tf.reduce_sum(xentropy, axis=1)
    # # average across the samples
    # rec_loss = tf.reduce_mean(rec_loss, name="reconstruction_loss")
    #
    # return rec_loss
    #
    if (output_activation == tf.nn.sigmoid):
        rec_loss = tf.losses.sigmoid_cross_entropy(tf.clip_by_value(X, eps, 1 - eps), x_raw, W)
    else:
        rec_loss = tf.losses.mean_squared_error(X, x, W)

    # re-scale the loss to the original dims (making sure it balances correctly with the latent loss)
    rec_loss = rec_loss * tf.cast(tf.reduce_prod(tf.shape(W)), dtype=tf.float32) / tf.reduce_sum(W)
    rec_loss = D * I * rec_loss

    return rec_loss

def latent_loss(z, mu_c, sigma2_c, phi_c, mu_tilde, log_sigma2_tilde, K, eps=1e-10):
    sigma2_tilde = tf.exp(log_sigma2_tilde)
    log_sigma2_c = tf.math.log(eps + sigma2_c)
    if K == 1:  # ordinary VAE
        latent_loss = tf.reduce_mean(input_tensor=0.5 * tf.reduce_sum(
            input_tensor=sigma2_tilde + tf.square(mu_tilde) - 1 - log_sigma2_tilde,
            axis=1
        ))
    else:
        log_2pi = tf.math.log(2 * np.pi)
        log_phi_c = tf.math.log(eps + phi_c)

        def log_pdf(z):
            def f(i):
                return - 0.5 * (log_sigma2_c[i] + log_2pi + tf.math.square(z - mu_c[i]) / sigma2_c[i])
                # return - tf.square(z - mu[i]) / 2.0 / (eps + sigma2[i]) - tf.math.log(
                #     eps + 2.0 * np.pi * sigma2[i]) / 2.0

            return tf.transpose(a=tf.map_fn(f, np.arange(K), tf.float32), perm=[1, 0, 2])

        log_p = log_phi_c + tf.reduce_sum(input_tensor=log_pdf(z), axis=2)
        lse_p = tf.reduce_logsumexp(input_tensor=log_p, keepdims=True, axis=1)
        log_gamma_c = log_p - lse_p

        gamma_c = tf.exp(log_gamma_c)

        # latent loss: E[log p(z|c) + log p(c) - log q(z|x) - log q(c|x)]
        term1 = tf.math.log(eps + sigma2_c)
        f2 = lambda i: sigma2_tilde / (eps + sigma2_c[i])
        term2 = tf.transpose(a=tf.map_fn(f2, np.arange(K), tf.float32), perm=[1, 0, 2])
        f3 = lambda i: tf.square(mu_tilde - mu_c[i]) / (eps + sigma2_c[i])
        term3 = tf.transpose(a=tf.map_fn(f3, np.arange(K), tf.float32), perm=[1, 0, 2])

        latent_loss1 = 0.5 * tf.reduce_sum(
            input_tensor=gamma_c * tf.reduce_sum(input_tensor=term1 + term2 + term3, axis=2), axis=1)
        # latent_loss2 = - tf.reduce_sum(gamma_c * tf.log(eps + phi_c / (eps + gamma_c)), axis=1)
        latent_loss2 = - tf.reduce_sum(input_tensor=gamma_c * (log_phi_c - log_gamma_c), axis=1)
        latent_loss3 = - 0.5 * tf.reduce_sum(input_tensor=1 + log_sigma2_tilde, axis=1)
        # average across the samples
        latent_loss1 = tf.reduce_mean(input_tensor=latent_loss1)
        latent_loss2 = tf.reduce_mean(input_tensor=latent_loss2)
        latent_loss3 = tf.reduce_mean(input_tensor=latent_loss3)
        # add the different terms
        latent_loss = latent_loss1 + latent_loss2 + latent_loss3
    return latent_loss