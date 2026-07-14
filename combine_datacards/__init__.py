"""
combine_datacards -- TauKITFlow's own analysis-specific CombineHarvester driver code.

Relocated from ``/ceph/.../CMSSW_15_0_2/src/CombineHarvester/SMRun2Legacy`` (the
``run3_htt`` branch of https://github.com/KIT-CMS/SMRun2Legacy) as part of Phase 2d
of the TauKITFlow rewrite. See STATUS.md ("## Phase 2d") for the full relocation
record, naming decision, and systematics-naming reconciliation with
``config/shapes/variations.py``.

What lives here is TauKITFlow's *own* SM H->tautau category/process/systematics
definitions and the datacard-writing orchestration built on top of
CombineHarvester -- not CombineHarvester itself. CombineHarvester / Combine /
CMSSW remain an external dependency, consumed only via ``CombineHarvester.CombineTools``
(available after sourcing ``utils/setup_cmssw.sh``) -- nothing under
CombineHarvester/CombineTools or CombineHarvester/CombinePdfs was copied here.
"""
