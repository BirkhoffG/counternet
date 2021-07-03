from counternet.cf_explainer import VanillaCF
from counternet.pipeline import Experiment
from counternet.model import CounterNetModel
from counternet.utils import load_configs
from counternet.import_essentials import Path

experiment = Experiment(explainers = [VanillaCF], m_configs=[load_configs(Path('assets/configs/adult.json'))])
experiment.run()
