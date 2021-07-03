# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/02b_counter_net.ipynb (unless otherwise specified).

__all__ = ['pl_logger', 'ABCBaseModule', 'BaseModule', 'PredictiveTrainingModule', 'CFNetTrainingModule']

# Cell
from .import_essentials import *
from .utils.all import *
from .evaluation import SensitivityMetric, ProximityMetric
from .cf_explainer import GlobalExplainerBase

pl_logger = logging.getLogger('lightning').setLevel(logging.ERROR)

# Cell
class ABCBaseModule(ABC):
    @abstractmethod
    def model_forward(self, *x):
        raise NotImplementedError

    @abstractmethod
    def forward(self, *x):
        raise NotImplementedError

    @abstractmethod
    def predict(self, *x):
        raise NotImplementedError

# Cell
class BaseModule(pl.LightningModule, ABCBaseModule):
    def __init__(self, configs: Dict[str, Any]):
        super().__init__()
        self.save_hyperparameters(configs)

        # read data
        self.data = pd.read_csv(Path(configs['data_dir']))
        self.continous_cols = configs['continous_cols']
        self.discret_cols = configs['discret_cols']
        self.__check_cols()

        # set training configs
        self.lr = configs['lr']
        self.batch_size = configs['batch_size']
        self.dropout = configs['dropout'] if 'dropout' in configs.keys() else 0.3
        self.lambda_1 = configs['lambda_1'] if 'lambda_1' in configs.keys() else 1
        self.lambda_2 = configs['lambda_2'] if 'lambda_2' in configs.keys() else 1
        self.lambda_3 = configs['lambda_3'] if 'lambda_3' in configs.keys() else 1
        self.threshold = configs['threshold'] if 'threshold' in configs.keys() else 1
        self.smooth_y = configs['smooth_y'] if 'smooth_y' in configs.keys() else True

        # loss functions
        self.loss_func_1 = get_loss_functions(configs['loss_1']) if 'loss_1' in configs.keys() else get_loss_functions("mse")
        self.loss_func_2 = get_loss_functions(configs['loss_2']) if 'loss_2' in configs.keys() else get_loss_functions("mse")
        self.loss_func_3 = get_loss_functions(configs['loss_3']) if 'loss_3' in configs.keys() else get_loss_functions("mse")

        # set model configss
        self.enc_dims = configs['encoder_dims'] if 'encoder_dims' in configs.keys() else []
        self.dec_dims = configs['decoder_dims'] if 'decoder_dims' in configs.keys() else []
        self.exp_dims = configs['explainer_dims'] if 'explainer_dims' in configs.keys() else []

        # log graph
        self.example_input_array = torch.randn((1, self.enc_dims[0]))

    def __check_cols(self):
        assert sorted(list(self.data.columns[:-1])) == sorted(self.continous_cols + self.discret_cols), \
            f"data columns ({sorted(list(self.data.columns[:-1]))}) is not the same as continous_cols and discret_cols ({sorted(self.continous_cols + self.discret_cols)})"
        self.data = self.data.astype(
            {col: np.float for col in self.continous_cols})

    def __check_cat_size(self, X_cat: torch.Tensor, categories: List[List[Any]]):
        n = 0
        for cat in categories:
            n += len(cat)
        return X_cat.size(-1) == n

    def training_epoch_end(self, outs):
        if self.current_epoch == 0:
            self.logger.log_hyperparams(self.hparams)

    def prepare_data(self):
        # TODO Decouple data preparision and use `LightningDataModule`
        # 70% for training, 10% for validation, 20% for testing
        X, y = split_X_y(self.data)

        # preprocessing
        self.scaler = MinMaxScaler()
        self.ohe = OneHotEncoder()
        X_cont = self.scaler.fit_transform(X[self.continous_cols]) if self.continous_cols else np.array([[] for _ in range(len(X))])
        X_cat = self.ohe.fit_transform(X[self.discret_cols]) if self.discret_cols else np.array([[] for _ in range(len(X))])
        X = torch.cat((X_cont, X_cat), dim=1)

        # init categorical normalizer to enable categorical features to be one-hot-encoding format
        cat_arrays = self.ohe.categories_ if self.discret_cols else []
        self.cat_normalizer = CategoricalNormalizer(cat_arrays, cat_idx=len(self.continous_cols))
        assert self.__check_cat_size(X_cat, cat_arrays)

        # init sensitivity metric
        self.sensitivity = SensitivityMetric(
            predict_fn=self.predict, scaler=self.scaler, cat_idx=len(self.continous_cols), threshold=self.threshold)

        print(f"x_cont: {X_cont.size()}, x_cat: {X_cat.size()}")
        print(f"categories: {cat_arrays}")
        print("X shape: ", X.size())

        assert X.size(-1) == self.enc_dims[0],\
            f'The input dimension X (shape: {X.shape[-1]})  != encoder_dims[0]: {self.enc_dims}'

        # prepare train & test
        train, val, test = train_val_test_split(X, y)
        self.train_dataset = TensorDataset(*train)
        self.val_dataset = TensorDataset(*val)
        self.test_dataset = TensorDataset(*test)

    def train_dataloader(self):
        return DataLoader(self.train_dataset, batch_size=self.batch_size,
                          pin_memory=True, shuffle=True, num_workers=0)

    def val_dataloader(self):
        return DataLoader(self.val_dataset, batch_size=self.batch_size,
                          pin_memory=True, shuffle=False, num_workers=0)

    def test_dataloader(self):
        return DataLoader(self.test_dataset, batch_size=self.batch_size,
                          pin_memory=True, shuffle=False, num_workers=0)

# Cell
class PredictiveTrainingModule(BaseModule):
    def __init__(self, configs: Dict[str, Any]):
        super().__init__(configs)
        # define metrics
        self.val_acc = Accuracy()

    def forward(self, *x):
        return self.model_forward(x)

    def predict(self, x):
        y_hat = self(x)
        return torch.round(y_hat)

    def configure_optimizers(self):
        return torch.optim.Adam([p for p in self.parameters() if p.requires_grad], lr=self.lr)

    def training_step(self, batch, batch_idx):
        # batch
        *x, y = batch
        # fwd
        y_hat = self(*x)
        # loss
        if self.smooth_y:
            y = smooth_y(y)
        loss = F.binary_cross_entropy(y_hat, y)

        # Logging to TensorBoard
        self.log('train/train_loss_1', loss, on_step=False, on_epoch=True, prog_bar=False, logger=True)

        return loss

    def validation_step(self, batch, batch_idx):
        # batch
        *x, y = batch
        # fwd
        y_hat = self(*x)
        # loss
        loss = F.binary_cross_entropy(y_hat, y)

        self.log('val/val_loss', loss, on_step=False, on_epoch=True, prog_bar=False, logger=True)
        self.log('val/pred_accuracy', self.val_acc(y_hat, y.int()), on_step=False, on_epoch=True, sync_dist=True)

# Cell
class CFNetTrainingModule(BaseModule, GlobalExplainerBase):
    def __init__(self, configs: Dict[str, Any]):
        super().__init__(configs)
        # define metrics
        self.pred_acc = Accuracy()
        self.cf_acc = Accuracy()
        self.proximity = ProximityMetric()

    def forward(self, x, hard: bool=False):
        """hard: categorical features in counterfactual is one-hot-encoding or not"""
        y, c = self.model_forward(x)
        c = self.cat_normalizer.normalize(c, hard=hard)
        return y, c

    def predict(self, x):
        """x has not been preprocessed"""
        y_hat, _ = self.model_forward(x)
        return torch.round(y_hat)

    def generate_cf(self, x, clamp=False):
        self.freeze()
        y, c = self.model_forward(x)
        if clamp:
            c = torch.clamp(c, 0., 1.)
        return self.cat_normalizer.normalize(c, hard=True)

    def _logging_loss(self, *loss, stage: str, on_step: bool = False):
        for i, l in enumerate(loss):
            self.log(f'{stage}/{stage}_loss_{i+1}', l, on_step=on_step, on_epoch=True, prog_bar=False, logger=True, sync_dist=True)

    def _loss_functions(self, x, c, y, y_hat, y_prime=None, is_val=False):
        """
        x: input value
        c: conterfactual example
        y: ground truth
        y_hat: predicted result
        y_prime_mode: 'label' or 'predicted'
        """
        # flip zero/one
        if y_prime == None:
            y_prime = flip_binary(y_hat)

        c_y, _ = self(c)
        # loss functions
        if self.smooth_y and not is_val:
            y = smooth_y(y)
            y_prime = smooth_y(y_prime)
        l_1 = self.loss_func_1(y_hat, y)
        l_2 = self.loss_func_2(x, c)
        l_3 = self.loss_func_3(c_y, y_prime)

        return l_1, l_2, l_3

    def configure_optimizers(self):
        opt_1 = torch.optim.Adam([p for p in self.parameters() if p.requires_grad], lr=self.lr)
        opt_2 = torch.optim.Adam([p for p in self.parameters() if p.requires_grad], lr=self.lr)
        return (opt_1, opt_2)

    def predictor_step(self, l_1, l_3):
        p_loss = self.lambda_1 * l_1 # + self.lambda_3 * l_3
        self.log('train/p_loss', p_loss, on_step=False, on_epoch=True, sync_dist=True)
        return p_loss

    def explainer_step(self, l_2, l_3):
        e_loss = self.lambda_2 * l_2 + self.lambda_3 * l_3
        self.log('train/e_loss', e_loss, on_step=False, on_epoch=True, sync_dist=True)
        return e_loss

    def training_step(self, batch, batch_idx, optimizer_idx):
        # batch
        x, y = batch
        # fwd
        y_hat, c = self(x)
        # loss
        l_1, l_2, l_3 = self._loss_functions(x, c, y, y_hat)

        result = 0
        if optimizer_idx == 0:
            result = self.predictor_step(l_1, l_3)

        if optimizer_idx == 1:
            result = self.explainer_step(l_2, l_3)

        # Logging to TensorBoard by default
        self._logging_loss(l_1, l_2, l_3, stage='train', on_step=False)
        return result

    def validation_step(self, batch, batch_idx):
        # batch
        x, y = batch

        # fwd
        y_hat, c = self(x, hard=True)
        c_y, _ = self(c)

        # loss
        l_1, l_2, l_3 = self._loss_functions(x, c, y, y_hat, is_val=True)
        loss = self.lambda_1 * l_1 + self.lambda_2 * l_2 + self.lambda_3 * l_3

        # logging val loss
        self._logging_loss(l_1, l_2, l_3, stage='val', on_step=False)

        # metrics
        metrics = {
            'val/val_loss': loss, 'val/pred_accuracy': self.pred_acc(torch.round(y_hat), y.int()),
            'val/cf_proximity': self.proximity(x, c), 'val/sensitivity': self.sensitivity(x, c, c_y),
            'val/cf_accuracy': self.cf_acc(torch.round(c_y), flip_binary(y_hat).int()),
        }
        self.log_dict(metrics, on_step=False, on_epoch=True, sync_dist=True)