from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def _json_file(path: str | Path, *, max_bytes: int = 64 * 1024 * 1024) -> dict:
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"JSON file does not exist: {source}")
    if source.stat().st_size > max_bytes:
        raise ValueError(f"JSON file exceeds {max_bytes} bytes: {source}")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON file: {source}") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON document must contain an object")
    return value


def _manifest(path: str):
    from .autonomy.training_contracts import dataset_manifest_from_dict

    return dataset_manifest_from_dict(_json_file(path))


def _splits(manifest, args):
    return manifest.split(
        train=args.train_fraction,
        validation=args.validation_fraction,
        test=args.test_fraction,
        salt=args.split_salt,
    )


def _loader_config(args):
    from .autonomy.learning_dataset import DatasetLoaderConfig

    return DatasetLoaderConfig(
        history_steps=args.history_steps,
        stride=args.stride,
        image_height=args.image_height,
        image_width=args.image_width,
        max_gap_s=args.max_gap_s,
        future_steps=args.future_steps,
        max_agents=args.max_agents,
        verify_frame_hashes=not args.no_verify_frame_hashes,
    )


def _profile(_args) -> int:
    from .autonomy.learned_world import world_model_profile
    from .autonomy.learning_provenance import provenance_profile
    from .autonomy.training import training_profile
    from .autonomy.training_contracts import training_contract_profile
    from .autonomy.world_model_export import export_profile

    print(json.dumps({
        "data_contract": training_contract_profile(),
        "model": world_model_profile(),
        "training": training_profile(),
        "provenance": provenance_profile(),
        "export": export_profile(),
    }, indent=2))
    return 0


def _manifest_validate(args) -> int:
    manifest = _manifest(args.manifest)
    split = _splits(manifest, args)
    from .autonomy.learning_dataset import split_hashes

    print(json.dumps({
        "dataset_id": manifest.dataset_id,
        "version": manifest.version,
        "samples": len(manifest.samples),
        "manifest_sha256": manifest.sha256(),
        "split_counts": {name: len(values) for name, values in split.items()},
        "split_sha256": split_hashes(split),
        "required_cameras": list(manifest.required_cameras),
        "valid": True,
    }, indent=2))
    return 0


def _dataset_inspect(args) -> int:
    from .autonomy.learning_dataset import SequenceWindowDataset

    manifest = _manifest(args.manifest)
    split = _splits(manifest, args)
    selected = None if args.split == "all" else split[args.split]
    dataset = SequenceWindowDataset(
        manifest,
        frame_roots=args.frame_root,
        sample_ids=selected,
        config=_loader_config(args),
    )
    profile = dataset.profile()
    profile["split"] = args.split
    profile["manifest_sha256"] = manifest.sha256()
    print(json.dumps(profile, indent=2))
    return 0


def _require_torch():
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("PyTorch is required; install vision-shark-app[learning]") from exc
    return torch


def _training_objects(args):
    torch = _require_torch()
    from .autonomy.learned_world import WorldModelConfig, build_torch_world_model
    from .autonomy.learning_dataset import SequenceWindowDataset

    manifest = _manifest(args.manifest)
    split = _splits(manifest, args)
    loader_cfg = _loader_config(args)
    train_dataset = SequenceWindowDataset(manifest, frame_roots=args.frame_root, sample_ids=split["train"], config=loader_cfg)
    validation_dataset = SequenceWindowDataset(manifest, frame_roots=args.frame_root, sample_ids=split["validation"], config=loader_cfg)
    model_cfg = WorldModelConfig(
        camera_count=len(train_dataset.camera_ids),
        image_channels=3,
        ego_state_dim=len(loader_cfg.ego_fields),
        hidden_dim=args.hidden_dim,
        temporal_layers=args.temporal_layers,
        bev_height=args.bev_height,
        bev_width=args.bev_width,
        future_steps=args.future_steps,
        future_dt_s=args.future_dt_s,
        trajectory_modes=args.trajectory_modes,
        max_agents=args.max_agents,
        agent_state_dim=4,
    )
    model = build_torch_world_model(model_cfg)
    generator = torch.Generator().manual_seed(args.seed)
    train_loader = torch.utils.data.DataLoader(
        train_dataset,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=args.workers,
        generator=generator,
    )
    validation_loader = torch.utils.data.DataLoader(
        validation_dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.workers,
    )
    return manifest, split, loader_cfg, model_cfg, model, train_loader, validation_loader


def _train(args) -> int:
    from .autonomy.training import TrainingConfig, fit_world_model, save_checkpoint
    from .autonomy.world_model_evaluator import evaluate_model_batches, rank_hard_cases
    from .autonomy.world_model_export import export_world_model_onnx, validate_onnx_artifact

    manifest, split, loader_cfg, model_cfg, model, train_loader, validation_loader = _training_objects(args)
    training_cfg = TrainingConfig(
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        weight_decay=args.weight_decay,
        gradient_clip_norm=args.gradient_clip_norm,
        seed=args.seed,
        device=args.device,
    )
    result = fit_world_model(
        model,
        lambda: train_loader,
        lambda: validation_loader,
        training=training_cfg,
    )
    evaluation = evaluate_model_batches(model, validation_loader, device=args.device)
    hard_cases = rank_hard_cases(evaluation, limit=args.hard_case_limit)
    checkpoint = save_checkpoint(
        model,
        args.output,
        model_config=model_cfg,
        training_config=training_cfg,
        dataset_sha256=manifest.sha256(),
        metrics=evaluation["aggregate"],
        extra={
            "dataset_id": manifest.dataset_id,
            "dataset_version": manifest.version,
            "split_counts": {name: len(values) for name, values in split.items()},
            "loader_config": {
                "history_steps": loader_cfg.history_steps,
                "stride": loader_cfg.stride,
                "image_height": loader_cfg.image_height,
                "image_width": loader_cfg.image_width,
                "max_gap_s": loader_cfg.max_gap_s,
                "future_steps": loader_cfg.future_steps,
                "max_agents": loader_cfg.max_agents,
                "ego_fields": list(loader_cfg.ego_fields),
            },
            "validation_hard_cases": hard_cases,
        },
    )
    export = None
    if args.onnx:
        export = export_world_model_onnx(
            model,
            args.onnx,
            config=model_cfg,
            history_steps=loader_cfg.history_steps,
            image_height=loader_cfg.image_height,
            image_width=loader_cfg.image_width,
            device=args.device,
        )
        export["validation"] = validate_onnx_artifact(args.onnx)
    registry = None
    if args.registry:
        from .autonomy.learning_provenance import register_dataset_manifest, register_model_checkpoint
        from .model_registry import ProvenanceRegistry

        registry_store = ProvenanceRegistry(args.registry)
        dataset_name = f"{manifest.dataset_id}:{manifest.version}"
        try:
            register_dataset_manifest(
                registry_store,
                manifest,
                license_id=args.dataset_license,
                split=split,
                metadata={"source": "vision-shark-learn train"},
            )
        except ValueError as exc:
            if "already registered" not in str(exc):
                raise
        registry = register_model_checkpoint(
            registry_store,
            model_name=args.model_name,
            checkpoint_path=args.output,
            dataset_names=[dataset_name],
            evaluation=evaluation["aggregate"],
            metadata={"world_model_config": model_cfg.as_dict()},
        )
    print(json.dumps({
        "fit": result,
        "evaluation": evaluation["aggregate"],
        "hard_cases": hard_cases,
        "checkpoint": checkpoint,
        "onnx": export,
        "registry": registry,
    }, indent=2))
    return 0


def _read_checkpoint_sidecar(checkpoint: str | Path) -> dict:
    path = Path(checkpoint)
    sidecar = path.with_suffix(path.suffix + ".json")
    if not sidecar.is_file():
        raise ValueError("checkpoint metadata sidecar is required")
    return _json_file(sidecar, max_bytes=8 * 1024 * 1024)


def _evaluate(args) -> int:
    torch = _require_torch()
    from .autonomy.learned_world import WorldModelConfig, build_torch_world_model
    from .autonomy.learning_dataset import DatasetLoaderConfig, SequenceWindowDataset
    from .autonomy.training import load_checkpoint
    from .autonomy.world_model_evaluator import evaluate_model_batches, rank_hard_cases

    metadata = _read_checkpoint_sidecar(args.checkpoint)
    model_cfg = WorldModelConfig(**dict(metadata.get("model_config") or {}))
    model_cfg.validate()
    loader_meta = dict((metadata.get("extra") or {}).get("loader_config") or {})
    manifest = _manifest(args.manifest)
    split = _splits(manifest, args)
    loader_cfg = DatasetLoaderConfig(
        history_steps=int(loader_meta.get("history_steps", args.history_steps)),
        stride=int(loader_meta.get("stride", args.stride)),
        image_height=int(loader_meta.get("image_height", args.image_height)),
        image_width=int(loader_meta.get("image_width", args.image_width)),
        max_gap_s=float(loader_meta.get("max_gap_s", args.max_gap_s)),
        future_steps=model_cfg.future_steps,
        max_agents=model_cfg.max_agents,
        ego_fields=tuple(loader_meta.get("ego_fields") or ()) or DatasetLoaderConfig().ego_fields,
        verify_frame_hashes=not args.no_verify_frame_hashes,
    )
    selected = split[args.split]
    dataset = SequenceWindowDataset(manifest, frame_roots=args.frame_root, sample_ids=selected, config=loader_cfg)
    loader = torch.utils.data.DataLoader(dataset, batch_size=args.batch_size, shuffle=False, num_workers=args.workers)
    model = build_torch_world_model(model_cfg)
    load_checkpoint(model, args.checkpoint, device=args.device)
    evaluation = evaluate_model_batches(model, loader, device=args.device)
    evaluation["hard_cases"] = rank_hard_cases(evaluation, limit=args.hard_case_limit)
    evaluation["split"] = args.split
    evaluation["checkpoint"] = str(args.checkpoint)
    print(json.dumps(evaluation, indent=2))
    return 0


def _register_dataset(args) -> int:
    from .autonomy.learning_provenance import register_dataset_manifest
    from .model_registry import ProvenanceRegistry

    manifest = _manifest(args.manifest)
    split = _splits(manifest, args)
    result = register_dataset_manifest(
        ProvenanceRegistry(args.registry),
        manifest,
        license_id=args.dataset_license,
        split=split,
    )
    print(json.dumps(result, indent=2))
    return 0


def _register_model(args) -> int:
    from .autonomy.learning_provenance import register_model_checkpoint
    from .model_registry import ProvenanceRegistry

    evaluation = _json_file(args.evaluation, max_bytes=16 * 1024 * 1024) if args.evaluation else {}
    result = register_model_checkpoint(
        ProvenanceRegistry(args.registry),
        model_name=args.model_name,
        checkpoint_path=args.checkpoint,
        dataset_names=args.dataset_name,
        evaluation=evaluation,
        calibration_sha256=args.calibration_sha256,
    )
    print(json.dumps(result, indent=2))
    return 0


def _add_split_arguments(parser):
    parser.add_argument("--train-fraction", type=float, default=0.8)
    parser.add_argument("--validation-fraction", type=float, default=0.1)
    parser.add_argument("--test-fraction", type=float, default=0.1)
    parser.add_argument("--split-salt", default="vision-shark")


def _add_loader_arguments(parser):
    parser.add_argument("--frame-root", action="append", default=[])
    parser.add_argument("--history-steps", type=int, default=4)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--image-height", type=int, default=128)
    parser.add_argument("--image-width", type=int, default=256)
    parser.add_argument("--max-gap-s", type=float, default=0.5)
    parser.add_argument("--future-steps", type=int, default=10)
    parser.add_argument("--max-agents", type=int, default=32)
    parser.add_argument("--no-verify-frame-hashes", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vision-shark-learn", description="Offline/shadow Vision Shark world-model training tools")
    sub = parser.add_subparsers(dest="command", required=True)

    profile = sub.add_parser("profile")
    profile.set_defaults(func=_profile)

    manifest = sub.add_parser("manifest-validate")
    manifest.add_argument("--manifest", required=True)
    _add_split_arguments(manifest)
    manifest.set_defaults(func=_manifest_validate)

    inspect = sub.add_parser("dataset-inspect")
    inspect.add_argument("--manifest", required=True)
    inspect.add_argument("--split", choices=["all", "train", "validation", "test"], default="all")
    _add_split_arguments(inspect)
    _add_loader_arguments(inspect)
    inspect.set_defaults(func=_dataset_inspect)

    train = sub.add_parser("train")
    train.add_argument("--manifest", required=True)
    train.add_argument("--output", required=True)
    train.add_argument("--onnx")
    train.add_argument("--epochs", type=int, default=20)
    train.add_argument("--learning-rate", type=float, default=3e-4)
    train.add_argument("--weight-decay", type=float, default=1e-4)
    train.add_argument("--gradient-clip-norm", type=float, default=5.0)
    train.add_argument("--seed", type=int, default=1337)
    train.add_argument("--device", default="cpu")
    train.add_argument("--batch-size", type=int, default=1)
    train.add_argument("--workers", type=int, default=0)
    train.add_argument("--hidden-dim", type=int, default=128)
    train.add_argument("--temporal-layers", type=int, default=1)
    train.add_argument("--bev-height", type=int, default=32)
    train.add_argument("--bev-width", type=int, default=32)
    train.add_argument("--future-dt-s", type=float, default=0.2)
    train.add_argument("--trajectory-modes", type=int, default=6)
    train.add_argument("--hard-case-limit", type=int, default=100)
    train.add_argument("--registry")
    train.add_argument("--model-name", default="vision-world-model")
    train.add_argument("--dataset-license", default="internal")
    _add_split_arguments(train)
    _add_loader_arguments(train)
    train.set_defaults(func=_train)

    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--manifest", required=True)
    evaluate.add_argument("--checkpoint", required=True)
    evaluate.add_argument("--split", choices=["validation", "test"], default="test")
    evaluate.add_argument("--device", default="cpu")
    evaluate.add_argument("--batch-size", type=int, default=1)
    evaluate.add_argument("--workers", type=int, default=0)
    evaluate.add_argument("--hard-case-limit", type=int, default=100)
    _add_split_arguments(evaluate)
    _add_loader_arguments(evaluate)
    evaluate.set_defaults(func=_evaluate)

    register_dataset = sub.add_parser("register-dataset")
    register_dataset.add_argument("--manifest", required=True)
    register_dataset.add_argument("--registry", required=True)
    register_dataset.add_argument("--dataset-license", default="internal")
    _add_split_arguments(register_dataset)
    register_dataset.set_defaults(func=_register_dataset)

    register_model = sub.add_parser("register-model")
    register_model.add_argument("--registry", required=True)
    register_model.add_argument("--model-name", required=True)
    register_model.add_argument("--checkpoint", required=True)
    register_model.add_argument("--dataset-name", action="append", required=True)
    register_model.add_argument("--evaluation")
    register_model.add_argument("--calibration-sha256")
    register_model.set_defaults(func=_register_model)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"vision-shark-learn: {exc}", file=sys.stderr)
        return 2


def cli() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    cli()
