import numpy as np
from numpy import ndarray
from collections import Counter
from typing import Dict, Union, Optional
from vader import VADER
from vader.hp_opt.abstract_optimization_job import AbstractOptimizationJob
from vader.hp_opt.clustering_utils import ClusteringUtils
from vader.hp_opt.common import ClusteringType


class FullOptimizationJob(AbstractOptimizationJob):

    def _cv_fold_step(self, X_train: ndarray, X_val: ndarray, W_train: Optional[ndarray],
                      W_val: Optional[ndarray]) -> Dict[str, Union[int, float]]:
        if self.n_consensus and self.n_consensus > 1:
            clustering_func = self._consensus_clustering
        else:
            clustering_func = self._single_clustering
        (y_pred,
         effective_k,
         train_reconstruction_loss,
         train_latent_loss,
         test_reconstruction_loss,
         test_latent_loss) = clustering_func(X_train, X_val, W_train)

        # calculate total loss
        alpha = self.params_dict["alpha"]
        train_total_loss = train_reconstruction_loss + alpha * train_latent_loss
        test_total_loss = test_reconstruction_loss + alpha * test_latent_loss

        # calculate y_true
        vader = self._fit_vader(X_val, W_val)
        # noinspection PyTypeChecker
        y_true = vader.cluster(X_val)

        # evaluate clustering
        adj_rand_index = ClusteringUtils.calc_adj_rand_index(y_pred, y_true)
        rand_index = ClusteringUtils.calc_rand_index(y_pred, y_true)
        prediction_strength = ClusteringUtils.calc_prediction_strength(y_pred, y_true)
        permuted_clustering_evaluation_metrics = ClusteringUtils.calc_permuted_clustering_evaluation_metrics(
            y_pred, y_true, self.n_perm
        )
        return {
            "train_reconstruction_loss": train_reconstruction_loss,
            "train_latent_loss": train_latent_loss,
            "train_total_loss": train_total_loss,
            "test_reconstruction_loss": test_reconstruction_loss,
            "test_latent_loss": test_latent_loss,
            "test_total_loss": test_total_loss,
            "effective_k": effective_k,
            "rand_index": rand_index,
            "rand_index_null": permuted_clustering_evaluation_metrics["rand_index"],
            "adj_rand_index": adj_rand_index,
            "adj_rand_index_null": permuted_clustering_evaluation_metrics["adj_rand_index"],
            "prediction_strength": prediction_strength,
            "prediction_strength_null": permuted_clustering_evaluation_metrics["prediction_strength"],
        }

    def _consensus_clustering(self, X_train: ndarray, X_val: ndarray, W_train: Optional[ndarray]) -> tuple:
        y_pred_repeats = []
        effective_k_repeats = []
        train_reconstruction_loss_repeats = []
        train_latent_loss_repeats = []
        test_reconstruction_loss_repeats = []
        test_latent_loss_repeats = []
        for i in range(self.n_consensus):
            self.seed = int(str(self.seed) + str(i)) if self.seed else None
            (
                y_pred,
                effective_k,
                train_reconstruction_loss,
                train_latent_loss,
                test_reconstruction_loss,
                test_latent_loss
            ) = self._single_clustering(X_train, X_val, W_train)
            y_pred_repeats.append(y_pred)
            effective_k_repeats.append(effective_k)
            train_reconstruction_loss_repeats.append(train_reconstruction_loss)
            train_latent_loss_repeats.append(train_latent_loss)
            test_reconstruction_loss_repeats.append(test_reconstruction_loss)
            test_latent_loss_repeats.append(test_latent_loss)
        effective_k = np.mean(effective_k_repeats)
        y_pred = ClusteringUtils.consensus_clustering(y_pred_repeats, round(float(effective_k)))
        train_reconstruction_loss = np.mean(train_reconstruction_loss_repeats)
        train_latent_loss = np.mean(train_latent_loss_repeats)
        test_reconstruction_loss = np.mean(test_reconstruction_loss_repeats)
        test_latent_loss = np.mean(test_latent_loss_repeats)
        return (
            y_pred,
            effective_k,
            train_reconstruction_loss,
            train_latent_loss,
            test_reconstruction_loss,
            test_latent_loss
        )

    def _single_clustering(self, X_train: ndarray, X_val: ndarray, W_train: Optional[ndarray]) -> tuple:
        # calculate y_pred
        vader = self._fit_vader(X_train, W_train)
        # noinspection PyTypeChecker
        test_loss_dict = vader.get_loss(X_val)
        train_reconstruction_loss, train_latent_loss = vader.reconstruction_loss[-1], vader.latent_loss[-1]
        test_reconstruction_loss, test_latent_loss = test_loss_dict["reconstruction_loss"], test_loss_dict[
            "latent_loss"]
        # noinspection PyTypeChecker
        effective_k = len(Counter(vader.cluster(X_train)))
        # noinspection PyTypeChecker
        y_pred = vader.cluster(X_val)
        return (
            y_pred,
            effective_k,
            train_reconstruction_loss,
            train_latent_loss,
            test_reconstruction_loss,
            test_latent_loss
        )

    def _fit_vader(self, X_train: ndarray, W_train: Optional[ndarray]) -> VADER:
        k = self.params_dict["k"]
        n_hidden = self.params_dict["n_hidden"]
        learning_rate = self.params_dict["learning_rate"]
        batch_size = self.params_dict["batch_size"]
        alpha = self.params_dict["alpha"]

        # noinspection PyTypeChecker
        vader = VADER(X_train=X_train, W_train=W_train, save_path=None, n_hidden=n_hidden, k=k, seed=self.seed,
                      learning_rate=learning_rate, recurrent=True, batch_size=batch_size, alpha=alpha)

        vader.pre_fit(n_epoch=10, verbose=False)
        vader.fit(n_epoch=self.n_epoch, verbose=False)
        return vader


if __name__ == "__main__":
    from vader.data_utils import read_adni_data, read_nacc_data

    input_data_file = "d:/workspaces/vader_data/ADNI/Xnorm.csv"
    input_data, input_weights = read_adni_data(input_data_file)
    params_dict = {
        "k": 4,
        "n_hidden": [32, 8],
        "learning_rate": 0.01,
        "batch_size": 16,
        "alpha": 1.0
    }
    seed = None
    n_consensus = 1
    n_epoch = 10
    n_splits = 2
    n_perm = 10
    verbose = True
    params_tuple = (input_data, input_weights, params_dict, seed,
                    n_consensus, n_epoch, n_splits, n_perm, verbose)
    job = FullOptimizationJob(*params_tuple)
    result = job.run()
    print(result)
