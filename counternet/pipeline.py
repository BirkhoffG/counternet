# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/00_pipeline.ipynb (unless otherwise specified).

__all__ = ['load_trained_model', 'ModelTrainer', 'CFGeneratorBase', 'LocalCFGenerator', 'is_predictive_model',
           'GlobalCFGenerator', 'Evaluator', 'Experiment']

# Cell
from .import_essentials import *
from .utils import *
from .training_module import BaseModule, CFNetTrainingModule
from .model import BaselinePredictiveModel, CounterNetModel
from .cf_explainer import ExplainerBase, LocalExplainerBase, GlobalExplainerBase, VanillaCF
from .evaluation import SensitivityMetric, proximity

# Cell
def load_trained_model(module: BaseModule, checkpoint_path: str, gpus : int = 0) -> BaseModule:
    # assuming checkpoint_path = f"{dict_path}/epoch={n_epoch}-step={step}.ckpt"
    if not os.path.exists(checkpoint_path):
        raise FileNotFoundError(f'{checkpoint_path} is not found.')

    n_iter = int(checkpoint_path.split("-")[0].split("=")[-1]) + 1
    # model = module.load_from_checkpoint(checkpoint_path)
    tmp_trainer = pl.Trainer(
        max_epochs=n_iter, resume_from_checkpoint=checkpoint_path, num_sanity_val_steps=0, gpus=gpus,
        logger=False, checkpoint_callback=False
    )
    tmp_trainer.fit(module)

    return module

# Cell
class ModelTrainer(object):
    def __init__(self,
                 model: BaseModule,
                 t_configs: Dict[str, Any],
                 callbacks: Optional[List[Callback]] = None,
                 description: Optional[str] = None,
                 debug: Optional[bool] = False,
                 logger: Optional[LightningLoggerBase] = None,
                 logger_name: str = "debug"):

        if logger is None:
            logger = pl_loggers.TestTubeLogger(
                Path('log/'), name=logger_name,
                description=description, debug=debug, log_graph=True
            )

        # model checkpoint
        self.checkpoint_callback = ModelCheckpoint(
            monitor='val/val_loss', save_top_k=3, mode='min'
        )

        # define callbacks
        if callbacks is None:
            callbacks = [self.checkpoint_callback]
        elif self._has_no_model_checkpoint(callbacks):
            callbacks += [self.checkpoint_callback]

        self.trainer = pl.Trainer(logger=logger, callbacks=callbacks, **t_configs)

        self.model = model

    def _has_no_model_checkpoint(self, callbacks: List[Callback]) -> bool:
        for callback in callbacks:
            if isinstance(callback, ModelCheckpoint):
                return False
        return True

    def fit(self, is_parallel=False):
        if is_parallel:
            logging.warning(
                f"parallel version has not been implemented\nUsing the single process training...")
        self.trainer.fit(self.model)

        return self.model

    def save_best_model(self, dir_path: Path):
        if not dir_path.is_dir():
            raise ValueError(f"'{dir_path}' is not a directory")
        best_model_path = Path(self.checkpoint_callback.best_model_path)
        shutil.copy(best_model_path, dir_path)
        return best_model_path

    def load_trained_model(self, checkpoint_path: str, gpus: int = 0) -> BaseModule:
        self.model = load_trained_model(
            self.model, checkpoint_path=checkpoint_path, gpus=gpus)
        return self.model

# Cell
class CFGeneratorBase(ABC):
    results = {
        "x": None, "cf": None, "y": None, "y_hat": None, "cf_y": None, "cf_y_hat": None,
        "sensitivity": None, "total_time": None, "avg_time": None, "cf_algo": None, "cat_idx": None
    }

    def __init__(self, cf_algo: ExplainerBase,
            pred_model: BaselinePredictiveModel, configs: Dict[str, Any] = {}):
        self.configs = configs
        self.pred_model = pred_model
        self.pred_model.freeze()

        self.cf_algo = cf_algo
        self.results.update({"cf_algo": type(cf_algo).__name__})
        self.dataset = pred_model.test_dataset
        self.sensitivity = pred_model.sensitivity

    def generate(self, dataset: Optional[TensorDataset]=None):
        raise NotImplementedError

# Cell
class LocalCFGenerator(CFGeneratorBase):
    def __init__(self, cf_algo: LocalExplainerBase,
            pred_model: BaselinePredictiveModel, configs: Dict[str, Any] = {}):
        super().__init__(cf_algo, pred_model, configs)
        # define cf_algo
        print(cf_algo)
        if not issubclass(type(cf_algo), LocalExplainerBase):
            raise ValueError(f"cf_algo should be an instance of `{LocalExplainerBase}`, but got `{type(cf_algo)}`. ")
        CFExplainer = type(cf_algo)
        pred_fn = pred_model.forward
        cat_normalizer = pred_model.cat_normalizer
        self.cf_algo = CFExplainer(pred_fn, cat_normalizer, configs)

        self.is_parallel = configs['is_parallel'] if 'is_parallel' in configs else True

    def gen_step(self, x):
        x = x.reshape(1, -1)
        cf = self.cf_algo.generate_cf(x)
        return x, cf

    def iterative_generate(self, size: int, dataset: TensorDataset):
        result = []
        start_time = time.time()
        for ix, (x, y) in enumerate(tqdm(dataset)):
            if ix < size:
                x, cf = self.__gen_step(x)
                result.append((x, cf))
        total_time = time.time() - start_time
        avg_time = total_time / size
        return result, {'total_time': total_time, 'avg_time': avg_time}

    def __unpack_x_cf(self, result: List[torch.Tensor]):
        X = torch.rand((len(result), result[0][0].size(-1)))
        cf_algo = X.clone()

        for ix, (x, cf) in enumerate(result):
            X[ix, :] = x
            cf_algo[ix, :] = cf
        return X, cf_algo

    def generate(self, dataset: Optional[TensorDataset]=None, debug: bool = False):        
        if dataset is None:
            dataset = self.pred_model.test_dataset
        size = len(dataset) if not debug else 3

        result = []

        if self.is_parallel:
            print(f"generating {size} cfs in parallel...")
            result = Parallel(n_jobs=-1, max_nbytes=None, verbose=False)(
                delayed(self.gen_step) (x=x)
                for ix, (x, y) in enumerate(tqdm(dataset)) if ix < size
            )
            print(f"evaluating speed by generating 50 cfs...")
            _, time = self.iterative_generate(50, dataset)
        else:
            print(f"generating {size} cfs...")
            result, time = self.iterative_generate(size, dataset)

        self.results.update(time)

        x, cf = self.__unpack_x_cf(result)
        _, y = dataset[:]
        y = y[:size]
        y_hat = self.pred_model.predict(x)
        cf_y = flip_binary(y_hat)
        cf_y_hat = self.pred_model.predict(cf)
        sensitivity = self.pred_model.sensitivity

        self.results.update({'x': x, 'cf': cf, 'y': y, 'y_hat': y_hat, 'cf_y': cf_y, 'cf_y_hat': cf_y_hat})
        self.results.update({'sensitivity': sensitivity(x, cf, cf_y).item(), 'cat_idx': sensitivity.cat_idx})

        return self.results

# Cell
# a temp workaround
def is_predictive_model(model: BaseModule):
    return callable(getattr(model, "predict", None))

# Cell
class GlobalCFGenerator(CFGeneratorBase):
    def __init__(self, cf_algo: GlobalExplainerBase,
            pred_model: Optional[BaselinePredictiveModel] = None, configs: Dict[str, Any] = {}) -> None:
        if not issubclass(type(cf_algo), GlobalExplainerBase):
            raise ValueError(f"cf_algo should be an instance of `{GlobalCFGenerator}`, but got `{type(cf_algo)}`")
        if not is_predictive_model(cf_algo) and pred_model is None:
            raise ValueError(f"pred_model should be passed when cf_algo is {type(cf_algo)}.")
        if is_predictive_model(cf_algo):
            pred_model = cf_algo
        super().__init__(cf_algo, pred_model, configs)

    def generate(self, dataset: Optional[TensorDataset]=None):
        if dataset is None:
            dataset = self.pred_model.test_dataset
        x, y = dataset[:]
        size = 1000

        print(f"generating {len(dataset)} cfs...")
        cf = self.cf_algo.generate_cf(x)

        print(f"evaluating speed...")
        start_time = time.time()
        for i, (sample, _) in enumerate(dataset):
            if i < size:
                self.cf_algo.generate_cf(sample.reshape(1, -1))
        total_time = time.time() - start_time
        avg_time = total_time / size

        y_hat = self.pred_model.predict(x)
        cf_y = flip_binary(y_hat)
        cf_y_hat = self.pred_model.predict(cf)
        sensitivity = self.pred_model.sensitivity
        for t in [x, cf, y, y_hat, cf_y, cf_y_hat]:
            print(t.size())

        self.results.update({'x': x, 'cf': cf, 'y': y, 'y_hat': y_hat, 'cf_y': cf_y, 'cf_y_hat': cf_y_hat})
        self.results.update({'sensitivity': sensitivity(x, cf, cf_y).item(), 'cat_idx': sensitivity.cat_idx})
        self.results.update({'total_time': total_time, 'avg_time': avg_time})
        return self.results

# Cell
class Evaluator(object):
    def __init__(self, configs: Dict[str, Any]={}):
        self.is_logging: bool = configs['is_logging'] if 'is_logging' in configs.keys() else True

    def eval(self, results: Dict[str, Any], dir_path: Path):
        if not dir_path.exists():
            raise ValueError(f"{dir_path} does not exist.")
        csv_path = dir_path / Path('metrics.csv')

        metrics = ['cat_proximity', 'cont_proximity', 'validity', 'sensitivity', 'time', 'pred_accuracy', 'proximity']
        # ['sparsity', 'diffs', 'total_num']

        if csv_path.exists():
            r = pd.read_csv(csv_path, index_col=0).to_dict()
            for metric in metrics:
                if metric not in r.keys():
                    r[metric] = dict()
        else:
            r = {metric:{} for metric in metrics}

        x, cf, y, y_hat, cf_y, cf_y_hat = results['x'], results['cf'], results['y'], \
            results['y_hat'], results['cf_y'], results['cf_y_hat']
        for t in [x, cf, y, y_hat, cf_y, cf_y_hat]:
            print(t.size())
        cat_idx, cf_name = results['cat_idx'], results['cf_algo']

        r['cont_proximity'][cf_name] = proximity(x[:, :cat_idx], cf[:, :cat_idx]).item()
        r['cat_proximity'][cf_name] = proximity(x[:, cat_idx:], cf[:, cat_idx:]).item()
        r['proximity'][cf_name] = r['cont_proximity'][cf_name] + r['cat_proximity'][cf_name]
        r['validity'][cf_name] = accuracy(cf_y.int(), cf_y_hat.int()).item()
        r['sensitivity'][cf_name] = results['sensitivity']
        r['time'][cf_name] = results['avg_time']
        r['pred_accuracy'][cf_name] = accuracy(y.int(), y_hat.int()).item()

        final_result_df = pd.DataFrame.from_dict(r)
        print(tabulate(final_result_df, headers = 'keys', tablefmt = 'psql'))
        if self.is_logging:
            final_result_df.to_csv(csv_path)
            torch.save(results, dir_path / f"{cf_name}_results.pt")
            print("Results has been saved!")
        return final_result_df

# Cell
class Experiment(object):
    def __init__(self, explainers: List[ExplainerBase],
            m_configs: List[Dict[str, Any]], t_configs: Optional[Dict[str, Any]] = None):
        self.explainers = explainers
        self.m_configs = m_configs
        self.use_pred_model = False # need a `BaselinePredictiveModel` or not
        self.pred_model = None      # init a `BaselinePredictiveModel` if neccesary
        if t_configs is None:
            self.t_configs = load_configs(Path('assets/configs/trainer.json'))
        else:
            self.t_configs = t_configs
        self.__check_explainers()

        self.evaluator = Evaluator(configs={'is_logging': True})

    def __is_type(self, instance):
        return isinstance(type(instance), type) or isinstance(type(instance), ABCMeta)
            
    def __check_explainers(self):
        for explainer in self.explainers: # explainer is already passed as a type
            if self.__is_type(explainer):
                explainer_type = deepcopy(explainer)
            else:
                explainer_type = type(explainer)
            if not issubclass(explainer_type, ExplainerBase):
                raise ValueError(f"The explainer should be a subclass of `{ExplainerBase}`, but got `{explainer_type}`")
            if not isinstance(explainer, CFNetTrainingModule):
                self.use_pred_model = True

    def __check_seeds(self, seeds: Optional[List[int]]):
        try:
            seeds = seeds if seeds is not None else [os.environ.get("PL_GLOBAL_SEED")]
        except (TypeError, ValueError):
            seed_everything(31); seeds = [31]
        return seeds

    def __make_dir(self, dataset_name: str, seed: List[int]):
        dir_path = Path(f'assets/results/{dataset_name}/seed-{seed}/')
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path

    def explainer_step(self, explainer: ExplainerBase, pred_model: BaselinePredictiveModel,
            m_config: Dict[str, Any], dir_path: Path):
        if not self.__is_type(explainer):
            CFExplainer = type(explainer)
        else:
            CFExplainer = explainer
        if issubclass(CFExplainer, GlobalExplainerBase):
            if issubclass(CFExplainer, CounterNetModel):
                model = CFExplainer(m_config)
            else: # need a predive model otherwise
                model = CFExplainer(m_config, pred_model)
            cfnet_trainer = ModelTrainer(model, self.t_configs)
            cfnet_trainer.fit()
            cfnet_trainer.save_best_model(dir_path)
            cf_generator = GlobalCFGenerator(model)
        else:
            print(f"Generating local explanation for {CFExplainer}")
            cf_generator = LocalCFGenerator(CFExplainer(pred_model.predict), pred_model)
        results = cf_generator.generate()
        self.evaluator.eval(results, dir_path)

    def experiment_step(self, m_config, seed: List[int]):
        if self.use_pred_model:
            pred_model = BaselinePredictiveModel(m_config)
        dataset_name = m_config['dataset_name']
        # logging dir
        dir_path = self.__make_dir(dataset_name, seed)
        # train a baseline predictive model
        pred_model_trainer = ModelTrainer(pred_model, self.t_configs)
        pred_model = pred_model_trainer.fit()
        for explainer in self.explainers:
            self.explainer_step(explainer, pred_model, m_config, dir_path)

    def run(self, seeds: Optional[List[int]] = None):
        seeds = self.__check_seeds(seeds)
        for seed in seeds:
            seed_everything(seed)
            for m_config in self.m_configs:
                self.experiment_step(m_config, seed)