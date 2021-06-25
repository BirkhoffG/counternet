# CounterNet: End-to-End Training of Counterfactual Aware Predictions

This is the official repository of the paper [CounterNet: End-to-End Training of Counterfactual Aware Predictions](). The purpose of the repository is only for research and reproduction of the paper's results. The audience should not expect to use the code directly in the deployed environemnt. 

The repository is built based on [nbdev](https://nbdev.fast.ai/). I would recommend you to check out [nbdev](https://nbdev.fast.ai/) if you enjoy writing code with Jupyter Notebook as I do. Further, it primarily leverages `Pytorch` and `Pytorch Lightning` for implementations of deep learning models. To install all the dependencies, you should run:

```
pip install -e .
```

Note:
- `pip install` will only install cpu-version of  `pytorch`. If you want to use GPU-version of `pytorch`, please follow [pytorch's official instruction](https://pytorch.org/get-started/locally/).
- As `Pytorch Lightning`'s API changes rapidly, it is not guaranteed that the code is compatible with other versions of Lightning (except the version that specified `settings.ini`).

## Useful commands for `nbdev`
### Build nbs to module

```
nbdev_build_lib
```

### Update nbs from module
```
nbdev_update_lib
```

### clean notebooks
```
nbdev_clean_nbs
```

### Test all modules
```
nbdev_test_nbs
```