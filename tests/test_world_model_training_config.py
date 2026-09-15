import pytest

from vision_shark.autonomy.training import TrainingConfig


def test_default_training_config_is_valid():
    TrainingConfig().validate()


def test_mixed_precision_requires_cuda():
    with pytest.raises(ValueError, match='requires a CUDA device'):
        TrainingConfig(device='cpu', mixed_precision=True).validate()


def test_training_config_rejects_invalid_learning_rate():
    with pytest.raises(ValueError, match='learning_rate'):
        TrainingConfig(learning_rate=0.0).validate()
