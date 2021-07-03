# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/01a_functional.ipynb (unless otherwise specified).

__all__ = ['is_predictive_model', 'check_input_type', 'check_object_input_type', 'l1_mean', 'get_loss_functions',
           'split_X_y', 'train_val_test_split', 'uniform', 'smooth_y', 'flip_binary']

# Comes from 00_pipeline.ipynb, cell
def is_predictive_model(model: BaseModule):
    return callable(getattr(model, "predict", None))

# Cell
from .import_essentials import *
import functools

# Cell
def _check_type(X):
    if not torch.is_tensor(X):
        if isinstance(X, np.ndarray):
            X = torch.from_numpy(X)
        elif isinstance(X, list):
            X = torch.tensor(X)
        elif isinstance(X, pd.DataFrame):
            X = X.to_numpy()
            X = torch.from_numpy(X)
        elif isinstance(X, pd.Series):
            X = X.values
            X = torch.tensor(X)
        else:
            raise ValueError(f'input X should be one of these types: [`list`, `pd.DataFrame`, `np.ndarray`, `torch.Tensor`], but got {type(X)}')
    return X.float()

# Cell
def check_input_type(func):
    """check if all inputs are torch.Tensor"""
    @functools.wraps(func)
    def wrapper_check_input_type(*args):
        new_args = []
        for X in list(args):
            new_args.append(_check_type(X))
        return func(*new_args)
    return wrapper_check_input_type

# Cell
def check_object_input_type(func):
    """check if all inputs are torch.Tensor"""
    @functools.wraps(func)
    def wrapper_check_input_type(ref, *args):
        new_args = [ref]
        for X in list(args):
            new_args.append(_check_type(X))
        return func(*new_args)
    return wrapper_check_input_type

# Comes from 02b_counter_net.ipynb, cell
def l1_mean(x, c):
    return F.l1_loss(x, c, reduction='mean') / x.abs().mean() # MAD

def get_loss_functions(f_name: str):
    _loss_functions = {
        'cross_entropy': F.binary_cross_entropy,
        'l1': F.l1_loss,
        'l1_mean': l1_mean,
        'mse': F.mse_loss
    }

    assert f_name in _loss_functions.keys(), \
        f'function name `{f_name}` is not in the loss function list {_loss_functions.keys()}'

    return _loss_functions[f_name]

# Comes from 02b_counter_net.ipynb, cell
def split_X_y(data: pd.DataFrame):
    X = data[data.columns[:-1]]
    y = data[data.columns[-1]]
    return X, y

@check_input_type
def train_val_test_split(X, y):
    assert len(X) == len(y)
    size = len(X)
    train_size = int(0.7 * size)    # 70% for training
    val_size = int(0.8 * size)      # 10% for validation

    return (
        (X[: train_size], y[: train_size]),
        (X[train_size:val_size], y[train_size:val_size]),
        (X[val_size:], y[val_size:])
    )

# Comes from 02b_counter_net.ipynb, cell
def uniform(shape: tuple, r1: float, r2: float, device=None):
    assert r1 < r2, f"Issue: r1 ({r1}) >= r2 ({r2})"
    return (r2 - r1) * torch.rand(*shape, device=device) + r1


def smooth_y(y, device=None):
    return torch.where(y == 1,
        uniform(y.size(), 0.8, 0.95, device=y.device),
        uniform(y.size(), 0.05, 0.2, device=y.device))

# Comes from 02b_counter_net.ipynb, cell
@check_input_type
def flip_binary(x):
    assert ((x < 0) & (x > 1)).sum() == 0
    return (1 - torch.round(x)).clone().detach()