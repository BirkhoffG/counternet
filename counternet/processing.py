# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/01c.preprocessing.ipynb (unless otherwise specified).

__all__ = ['ABCScaler', 'StandardScaler', 'MinMaxScaler', 'OneHotEncoder', 'NumpyDataset', 'PandasDataset',
           'CategoricalNormalizer']

# Cell
from .import_essentials import *
from .functional_utils import *
from .dataset import load_adult_income_dataset

# Cell
class ABCScaler(ABC):
    @abstractmethod
    def fit(self, X):
        raise NotImplementedError

    @abstractmethod
    def transform(self, X):
        raise NotImplementedError

    @abstractmethod
    def fit_transform(self, X):
        raise NotImplementedError

    @abstractmethod
    def inverse_transform(self, X):
        raise NotImplementedError

# Cell
class StandardScaler(ABCScaler):
    """rewrite `StandardScaler` object in sci-kit learn in pytorch to eliminate cpu-gpu communication time"""
    mean_, std_ = None, None

    @check_object_input_type
    def fit(self, X):
        self.mean_, self.std_ = torch.mean(X), torch.std(X)
        return self

    @check_object_input_type
    def transform(self, X):
        if (self.mean_ is None) or (self.std_ is None):
            raise NotImplementedError(f'The scaler has not been fitted.')
        return (X - self.mean_) / self.std_

    @check_object_input_type
    def fit_transform(self, X):
        self.mean_, self.std_ = torch.mean(X), torch.std(X)
        return (X - self.mean_) / self.std_

    @check_object_input_type
    def inverse_transform(self, X):
        return X * self.std_ + self.mean_

# Cell
class MinMaxScaler(ABCScaler):
    """rewrite `MinMaxScaler` object in sci-kit learn in pytorch to eliminate cpu-gpu communication time"""
    min_, max_ = None, None

    @check_object_input_type
    def fit(self, X):
        self.min_, self.max_ = torch.min(X), torch.max(X)
        assert self.min_ != self.max_, f"min(X) == max(X) is not allowed."
        return self

    @check_object_input_type
    def transform(self, X):
        if (self.min_ is None) or (self.max_ is None):
            raise NotImplementedError(f'The scaler has not been fitted.')
        return (X - self.min_) / (self.max_ - self.min_)

    @check_object_input_type
    def fit_transform(self, X):
        self.min_, self.max_ = torch.min(X), torch.max(X)
        assert self.min_ != self.max_, f"min(X) == max(X) is not allowed."
        return (X - self.min_) / (self.max_ - self.min_)

    @check_object_input_type
    def inverse_transform(self, X):
        return X * (self.max_ - self.min_) + self.min_

# Cell
# TODO need to check
class OneHotEncoder(object):
    categories_ = []
    drop_idx_ = None

    def __init__(self):
        from sklearn.preprocessing import OneHotEncoder
        self.enc = OneHotEncoder(sparse=False)

    def fit(self, X):
        self.enc.fit(X)
        # copy attributes
        self.categories_ = self.enc.categories_
        self.drop_idx_ = self.enc.drop_idx_
        return self

    def transform(self, X):
        return torch.from_numpy(self.enc.transform(X))

    def fit_transform(self, X):
        self.fit(X)
        return self.transform(X)

    def inverse_transform(self, X):
        assert isinstance(X, torch.Tensor)
        return self.enc.inverse_transform(X.cpu())

# Cell
class NumpyDataset(TensorDataset):
    def __init__(self, *arrs):
        super().__init__()
        # init tensors
        # small patch: skip continous or discrete array without content
        self.tensors = [torch.tensor(arr).float()
                        for arr in arrs if arr.shape[-1] != 0]
        assert all(self.tensors[0].size(0) == tensor.size(0)
                   for tensor in self.tensors)

    def data_loader(self, batch_size=128, shuffle=True, num_workers=4):
        return DataLoader(self, batch_size=batch_size, shuffle=shuffle, num_workers=num_workers)

    def features(self, test=False):
        return tuple(self.tensors[:-1] if not test else self.tensors)

    def target(self, test=False):
        return self.tensors[-1] if not test else None


class PandasDataset(NumpyDataset):
    def __init__(self, df: pd.DataFrame):
        cols = df.columns
        X = df[cols[:-1]].to_numpy()
        y = df[cols[-1]].to_numpy()
        super().__init__(X, y)

# Comes from 02b_counter_net.ipynb, cell
class CategoricalNormalizer(object):
    """implement post-processing step to enforce each elements
    in every category in the range of [0, 1] and output to 1.
    """
    def __init__(self, categories: List[List[Any]], cat_idx: int):
        self.categories = categories
        self.cat_idx = cat_idx

    def normalize(self, x, hard=False):
        cat_idx = self.cat_idx
        for col in self.categories:
            cat_end_idx = cat_idx + len(col)
            if hard:
                x[:, cat_idx: cat_end_idx] = F.gumbel_softmax(x[:, cat_idx: cat_end_idx].clone().detach(), hard=hard)
            else:
                x[:, cat_idx: cat_end_idx] = F.softmax(x[:, cat_idx: cat_end_idx].clone().detach(), dim=-1)
            cat_idx = cat_end_idx
        return x