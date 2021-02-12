import os
import traceback
import numpy as np
import pandas as pd
import multiprocessing as mp
from vader.hp_opt import common
from typing import List, Optional
from vader.hp_opt.param_grid_factory import ParamGridFactory
from vader.hp_opt.job.full_optimization_job import FullOptimizationJob
from vader.hp_opt.cv_results_aggregator import CVResultsAggregator
import uuid
from numpy import ndarray
from abc import ABC, abstractmethod
from vader import VADER
from vader.hp_opt import common
from typing import List, Dict, Union, Optional
from sklearn.model_selection import KFold
from numpy import ndarray
from collections import Counter
from typing import Dict, Union, Optional
from vader import VADER
from vader.hp_opt.job.abstract_optimization_job import AbstractOptimizationJob
from vader.utils.clustering_utils import ClusteringUtils
from vader.utils.data_utils import generate_x_w_y, read_adni_norm_data, generate_wtensor_from_xtensor
import optuna


class VADERBayesianOptimizer:
    SECONDS_IN_DAY = 86400

    def __init__(self, n_repeats: int = 10, n_proc: int = 1, n_trials: int = 100, n_consensus: int = 1,
                 n_epoch: int = 10, n_splits: int = 2, n_perm: int = 100, seed: Optional[int] = None,
                 output_folder: str = "."):
        self.n_trials = n_trials
        self.n_proc = n_proc
        self.n_repeats = n_repeats
        self.n_consensus = n_consensus
        self.n_epoch = n_epoch
        self.n_splits = n_splits
        self.n_perm = n_perm
        self.seed = seed

        # Configure output folders
        self.output_folder = output_folder
        self.output_repeats_dir = os.path.join(self.output_folder, "csv_repeats")
        self.output_trials_dir = os.path.join(self.output_folder, "csv_trials")
        self.failed_jobs_dir = os.path.join(self.output_folder, "failed_jobs")
        if not os.path.exists(self.output_repeats_dir):
            os.makedirs(self.output_repeats_dir, exist_ok=True)
        if not os.path.exists(self.output_trials_dir):
            os.makedirs(self.output_trials_dir, exist_ok=True)
        if not os.path.exists(self.failed_jobs_dir):
            os.makedirs(self.failed_jobs_dir, exist_ok=True)

        # Configure param grid
        self.k_list = [2, 3, 4, 5, 6]
        self.hyperparameters = ["n_hidden", "learning_rate", "batch_size", "alpha"]

        # Configure output files names
        self.run_id = f"n_trials{n_trials}_n_repeats{n_repeats}_n_splits{n_splits}_" \
                      f"n_consensus{n_consensus}_n_epoch{n_epoch}_n_perm{n_perm}_seed{seed}"
        self.output_pdf_report_file = os.path.join(self.output_folder, f"report_{self.run_id}.pdf")
        self.output_diffs_file = os.path.join(self.output_folder, f"diffs_{self.run_id}.csv")
        self.output_best_scores_file = os.path.join(self.output_folder, f"best_scores_{self.run_id}.csv")
        self.output_log_file = os.path.join(self.output_folder, f"{__name__}_{self.run_id}.log")

        # Configure logging
        # self.logger = common.log_manager.get_logger(__name__, log_file=self.output_log_file)
        self.logger = common.log_manager.get_logger(__name__)
        self.logger.info(f"{__name__} is initialized with run_id={self.run_id}")

    def __construct_jobs_params_list(self, input_data: np.ndarray, input_weights: np.ndarray) -> List[tuple]:
        jobs_params_list = [(input_data, input_weights, k) for k in self.k_list]
        return jobs_params_list

    def run_parallel_jobs(self, jobs_params_list: List[tuple]) -> pd.DataFrame:
        with mp.Pool(self.n_proc) as pool:
            cv_results_list = pool.map(self.run_cv_full_job, jobs_params_list)

        cv_results_df = pd.DataFrame(cv_results_list)
        return cv_results_df

    def run_cv_full_job(self, params_tuple: tuple) -> pd.Series:
        input_data = params_tuple[0]
        input_weights = params_tuple[1]
        k = params_tuple[2]

        self.logger.info(f"PROCESS k={k}")
        study_name = f'VaDER_k{k}'
        study = optuna.create_study(
            study_name=study_name,
            # storage=f"sqlite:///{study_name}.db",
            direction="maximize",
            load_if_exists=True
        )
        study.optimize(
            func=lambda trial: self.objective(trial, k, input_data, input_weights),
            n_trials=self.n_trials,
            timeout=self.SECONDS_IN_DAY,
            n_jobs=self.n_proc
        )
        result = {
            "k": k,
            "best_params": study.best_params,
            "best_value": study.best_value
        }
        self.logger.info(f"For k={k} best_params={study.best_params} with score={study.best_value}")
        return pd.Series(result)

    def __gen_repeats_files_from_trials_files(self):
        df_trials_list = []
        for entry in os.scandir(self.output_trials_dir):
            if entry.is_file() and entry.path.endswith(".csv"):
                df = pd.read_csv(entry.path)
                df_trials_list.append(df)
        df = pd.concat(df_trials_list, ignore_index=True)

        for i in range(self.n_repeats):
            ii = list(range(i, df.shape[0], self.n_repeats))
            df.iloc[ii].to_csv(os.path.join(self.output_repeats_dir, f"repeat_{i}.csv"), index=False)

    def run(self, input_data: np.ndarray, input_weights: np.ndarray) -> None:
        self.logger.info(f"Optimization has started. Data shape: {input_data.shape}")

        jobs_params_list = self.__construct_jobs_params_list(input_data, input_weights)
        self.logger.info(f"Number of jobs: {len(jobs_params_list)}")

        cv_results_df = self.run_parallel_jobs(jobs_params_list)
        cv_results_df.to_csv(self.output_best_scores_file, index=False)

        self.__gen_repeats_files_from_trials_files()
        aggregator = CVResultsAggregator.from_files(self.output_repeats_dir, self.hyperparameters)
        aggregator.plot_to_pdf(self.output_pdf_report_file)
        aggregator.save_to_csv(self.output_diffs_file)

        self.logger.info(f"Optimization has finished. See: {self.output_best_scores_file}")

        number_of_failed_jobs = len(os.listdir(self.failed_jobs_dir))
        if number_of_failed_jobs > 0:
            self.logger.warning(f"There are {number_of_failed_jobs} failed jobs. See: {self.failed_jobs_dir}")

    def run_cv_single_job(self, input_data, input_weights, params_dict, seed):
        job = FullOptimizationJob(
            data=input_data,
            weights=input_weights,
            params_dict=params_dict,
            seed=seed,
            n_consensus=self.n_consensus,
            n_epoch=self.n_epoch,
            n_splits=self.n_splits,
            n_perm=self.n_perm
        )
        try:
            self.logger.info(f"Job has started with id={job.cv_id} and job_params_dict={params_dict}")
            result = job.run()
            self.logger.info(f"Job has finished with id={job.cv_id} and job_params_dict={params_dict}")
        except Exception:
            error_message = f"Job failed: {job.cv_id} and job_params_dict={params_dict}\n{traceback.format_exc()}"
            log_file = os.path.join(self.failed_jobs_dir, f"{job.cv_id}.log")
            with open(log_file, "w") as f:
                f.write(error_message)
            self.logger.error(error_message)
            result = pd.Series(params_dict)
        return result

    def objective(self, trial, k, input_data, input_weights):
        trial_id = f"k{k}_trial{trial.number}"
        learning_rate = trial.suggest_loguniform("learning_rate", 1e-4, 1e-2)
        batch_size = trial.suggest_int("batch_size", 8, 128)
        n_hidden_1 = trial.suggest_int("n_hidden_1", 8, 128)
        n_hidden_2 = trial.suggest_int("n_hidden_2", 1, n_hidden_1)
        n_hidden = (n_hidden_1, n_hidden_2)

        params_dict = {
            "k": k,
            "n_hidden": n_hidden,
            "learning_rate": learning_rate,
            "batch_size": batch_size,
            "alpha": 1
        }
        repeats_results = []
        for i in range(self.n_repeats):
            seed = int(str(self.seed) + str(k) + str(trial.number) + str(i)) if self.seed else None
            result = self.run_cv_single_job(input_data, input_weights, params_dict, seed)
            repeats_results.append(result)
        results_df = pd.DataFrame(repeats_results)
        results_df.to_csv(os.path.join(self.output_trials_dir, f"{trial_id}.csv"), index=False)
        score = results_df["prediction_strength_diff"].mean() if "prediction_strength_diff" in results_df.columns else None
        return score


if __name__ == "__main__":
    x_tensor_with_nans = read_adni_norm_data("d:\\workspaces\\vader_data\\ADNI\\Xnorm.csv")
    W = generate_wtensor_from_xtensor(x_tensor_with_nans)
    X = np.nan_to_num(x_tensor_with_nans)
    optimizer = VADERBayesianOptimizer(
        n_repeats=5,
        n_proc=6,
        n_trials=5,
        n_consensus=1,
        n_epoch=20,
        n_splits=2,
        n_perm=10,
        seed=None,
        output_folder="d:\\workspaces\\vader_results\\Bayesian_test"
    )
    optimizer.run(X, W)
