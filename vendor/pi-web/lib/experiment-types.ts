import type { Experiment, ExperimentRun } from "../../../.pi/extensions/comms-experiments/engine";

export type ExperimentView = Omit<Experiment, "runs"> & { runs: Omit<ExperimentRun, "vector">[] };
