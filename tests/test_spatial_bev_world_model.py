import pytest

from vision_shark.autonomy.learned_world import WorldModelConfig, world_model_profile


def tiny_spatial_config(**overrides):
    values = {
        "camera_count": 2,
        "image_channels": 3,
        "ego_state_dim": 8,
        "hidden_dim": 32,
        "temporal_layers": 1,
        "bev_height": 4,
        "bev_width": 4,
        "future_steps": 3,
        "trajectory_modes": 2,
        "max_agents": 2,
        "agent_state_dim": 4,
        "use_camera_geometry": True,
        "use_spatial_bev": True,
        "spatial_token_height": 2,
        "spatial_token_width": 3,
        "attention_heads": 4,
    }
    values.update(overrides)
    return WorldModelConfig(**values)


def test_spatial_bev_requires_camera_geometry():
    with pytest.raises(ValueError, match="requires use_camera_geometry"):
        WorldModelConfig(use_spatial_bev=True, use_camera_geometry=False).validate()


def test_spatial_bev_attention_heads_must_divide_hidden_dim():
    with pytest.raises(ValueError, match="divisible"):
        tiny_spatial_config(hidden_dim=30, attention_heads=4).validate()


def test_spatial_bev_requires_geometry_contract_width():
    with pytest.raises(ValueError, match="calibration contract width"):
        tiny_spatial_config(camera_geometry_dim=17).validate()


def test_spatial_profile_reports_ray_and_bev_token_counts():
    profile = world_model_profile(tiny_spatial_config())
    assert profile["geometry_aware"] is True
    assert profile["spatial_bev"] is True
    assert profile["spatial_camera_tokens_per_camera"] == 6
    assert profile["bev_tokens"] == 16
    assert "camera-ray tokens" in profile["architecture"]


def _identity_geometry(torch, *, batch=1, history=2, cameras=2):
    geometry = torch.zeros(batch, history, cameras, 18, dtype=torch.float32)
    geometry[..., 0] = 0.8
    geometry[..., 1] = 0.8
    geometry[..., 2] = 0.5
    geometry[..., 3] = 0.5
    geometry[..., 4] = 16.0 / 9.0
    geometry[..., 5] = 9.0 / 16.0
    geometry[..., 6] = 1.0
    geometry[..., 10] = 1.0
    geometry[..., 14] = 1.0
    geometry[..., 17] = 1.2
    return geometry


def test_spatial_bev_forward_backward_shapes():
    torch = pytest.importorskip("torch")
    from vision_shark.autonomy.learned_world import build_torch_world_model, world_model_loss

    config = tiny_spatial_config()
    model = build_torch_world_model(config)
    cameras = torch.rand(1, 2, 2, 3, 32, 48)
    ego = torch.rand(1, 2, 8)
    geometry = _identity_geometry(torch)
    outputs = model(cameras, ego, geometry)

    assert tuple(outputs["occupancy_logits"].shape) == (1, 3, 4, 4)
    assert tuple(outputs["occupancy_flow"].shape) == (1, 3, 2, 4, 4)
    assert tuple(outputs["risk_logits"].shape) == (1, 3, 4, 4)
    assert tuple(outputs["agent_forecasts"].shape) == (1, 2, 3, 4)
    assert tuple(outputs["ego_trajectories"].shape) == (1, 2, 3, 4)
    assert tuple(outputs["camera_attention"].shape) == (1, 2, 2)
    assert torch.allclose(outputs["camera_attention"].sum(dim=-1), torch.ones(1, 2), atol=1e-5)

    target = {"ego_trajectory": torch.rand(1, 3, 4)}
    loss, components = world_model_loss(outputs, target)
    assert torch.isfinite(loss)
    assert "trajectory" in components
    loss.backward()
    assert any(parameter.grad is not None for parameter in model.parameters() if parameter.requires_grad)


def test_spatial_bev_onnx_export_roundtrip(tmp_path):
    torch = pytest.importorskip("torch")
    pytest.importorskip("onnx")
    from vision_shark.autonomy.learned_world import build_torch_world_model
    from vision_shark.autonomy.world_model_export import export_world_model_onnx, validate_onnx_artifact

    config = tiny_spatial_config()
    model = build_torch_world_model(config)
    destination = tmp_path / "spatial-world.onnx"
    metadata = export_world_model_onnx(
        model,
        destination,
        config=config,
        history_steps=2,
        image_height=32,
        image_width=48,
    )
    validated = validate_onnx_artifact(destination)
    assert metadata["geometry_aware"] is True
    assert "camera_geometry" in metadata["inputs"]
    assert validated["valid"] is True
    assert validated["geometry_aware"] is True
    assert validated["sha256"] == metadata["onnx_sha256"]
