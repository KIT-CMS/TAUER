MASS = "125"
CADI_LINE = "hig-26-018"
PHYSICS_MODEL = "HiggsAnalysis.CombinedLimit.PhysicsModel:multiSignalModel"
PHYSICS_MODEL_OPTIONS = [
    "--PO", f'"map=^.*/ggH{MASS}$:r_ggH[1,0,5]"',
    "--PO", f'"map=^.*/qqH{MASS}$:r_qqH[1,0,5]"',
]
