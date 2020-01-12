"""Train a transformer tagging model, using Huggingface's Transformers.

Tip: You can profile your program with

    py-spy record -o profile.svg --native --rate 20 -- python examples/scripts/transformers_tagger.py

The width of each block indicates the time spent within that function or within
its call stack. If a block is wider than its child, time is being spent there.
You should see that very little time is being spent within Thinc, indicating
that the computation is delegated to PyTorch efficiently.
"""
import random
import tqdm
import torch
from dataclasses import dataclass
from typing import List, Optional, Tuple, Callable
from pathlib import Path
from transformers import AutoTokenizer, AutoModel
import thinc.api
from thinc.model import Model
from thinc.api import PyTorchWrapper, Softmax, chain, with_array
from thinc.api import torch2xp, xp2torch, sequence_categorical_crossentropy
from thinc.types import Array2d, ArgsKwargs
from thinc.util import evaluate_model_on_arrays
import ml_datasets


CONFIG = """
[common]
starter = "distilbert-base-uncased"

[training]
batch_size = 5
n_epoch = 10
batch_per_update = 4

[optimizer]
@optimizers = "Adam.v1"

[optimizer.schedules.learn_rate]
@schedules = "warmup_linear.v1"
initial_rate = 0.001
warmup_steps = 3000
total_steps = 10000

[model]
@layers = "transformer_tagger_example.v0"

[model.tokenizer]
@layers = "transformers_tokenizer.v0"
name = ${common:starter}

[model.transformer]
@layers = "transformers_model.v0"
name = ${common:starter}

[model.output_layer]
@layers = "output_layer_example.v0"
"""


@dataclass
class TokensPlus:
    """Dataclass to hold the output of the Huggingface 'batch_encode_plus' method."""

    input_ids: torch.Tensor
    token_type_ids: torch.Tensor
    attention_mask: torch.Tensor
    input_len: List[int]
    overflowing_tokens: Optional[torch.Tensor] = None
    num_truncated_tokens: Optional[torch.Tensor] = None
    special_tokens_mask: Optional[torch.Tensor] = None


# @thinc.api.registry.layers("transformer_tagger_example.v0")
# def transformer_tagger_example(
#    tokenizer: Model[List[str], TokensPlus],
#    transformer: Model[TokensPlus, List[Array2d]],
#    output_layer: Model[List[Array2d], List[Array2d]],
# ) -> Model[List[str], List[Array2d]]:
#    return chain(tokenizer, transformer, output_layer)
@thinc.api.registry.layers("transformer_tagger_example.v0")
def transformer_tagger_example(
    tokenizer: Model, transformer: Model, output_layer: Model
) -> Model:
    return chain(tokenizer, transformer, output_layer)


@thinc.api.registry.layers("transformers_tokenizer.v0")
def transformers_tokenizer(name: str) -> Model[List[List[str]], List[TokensPlus]]:
    return Model(
        "tokenizer",
        _tokenizer_forward,
        attrs={"tokenizer": AutoTokenizer.from_pretrained(name)},
    )


def _tokenizer_forward(
    model, texts: List[List[str]], is_train
) -> Tuple[TokensPlus, Callable]:
    tokenizer = model.get_attr("tokenizer")
    token_data = tokenizer.batch_encode_plus(
        [(text, None) for text in texts],
        add_special_tokens=True,
        return_token_type_ids=True,
        return_attention_masks=True,
        return_input_lengths=True,
        return_tensors="pt",
    )
    return TokensPlus(**token_data), lambda d_tokens: d_tokens


@thinc.api.registry.layers("transformers_model.v0")
def transformers_model(name) -> Model[List[TokensPlus], List[Array2d]]:
    return PyTorchWrapper(
        AutoModel.from_pretrained(name),
        convert_inputs=convert_transformer_inputs,
        convert_outputs=convert_transformer_outputs,
    )


@thinc.api.registry.layers("output_layer_example.v0")
def output_layer_example() -> Model:
    return with_array(Softmax())


def convert_transformer_inputs(model, tokens: TokensPlus, is_train):
    kwargs = {"input_ids": tokens.input_ids, "attention_mask": tokens.attention_mask}
    return ArgsKwargs(args=(), kwargs=kwargs), lambda dX: []


def convert_transformer_outputs(model, inputs_outputs, is_train):
    layer_inputs, torch_outputs = inputs_outputs
    torch_tokvecs: torch.Tensor = torch_outputs[0]
    # Free the memory as soon as we can
    torch_outputs = None
    lengths = list(layer_inputs.input_len)
    tokvecs: List[Array2d] = model.ops.unpad(torch2xp(torch_tokvecs), lengths)
    # Remove the BOS and EOS markers.
    tokvecs = [arr[1:-1] for arr in tokvecs]

    def backprop(d_tokvecs: List[Array2d]) -> ArgsKwargs:
        # Restore entries for bos and eos markers.
        row = model.ops.alloc_f2d(1, d_tokvecs[0].shape[1])
        d_tokvecs = [model.ops.xp.vstack((row, arr, row)) for arr in d_tokvecs]
        return ArgsKwargs(
            args=(torch_tokvecs,),
            kwargs={"grad_tensors": xp2torch(model.ops.pad(d_tokvecs))},
        )

    return tokvecs, backprop


def evaluate_sequences(model, Xs: List[Array2d], Ys: List[Array2d], batch_size: int) -> float:
    correct = 0.0
    total = 0.0
    for batch in thinc.api.minibatch(zip(Xs, Ys), size=batch_size):
        X, Y = zip(*batch)
        Yh = model.predict(X)
        for yh, y in zip(Yh, Y):
            correct += (y.argmax(axis=1) == yh.argmax(axis=1)).sum()
            total += y.shape[0]
    return correct / total


def load_config(path: Optional[Path]):
    from thinc.api import Config, registry

    if path is None:
        config = Config().from_str(CONFIG)
    else:
        config = Config().from_disk(path)
    print(config["optimizer"]["schedules"])
    # The make_from_config function constructs objects for you, whenever
    # you have blocks with an @ key. For instance, in the optimizer block,
    # we write @optimizers = "Adam.v1". This tells Thinc to use the optimizers
    # registry to fetch the "Adam.v1" function. You can register your own
    # functions as well, and build up trees of objects.
    return registry.make_from_config(config)


def main(path: Optional[Path] = None):
    if thinc.api.prefer_gpu():
        print("Using gpu!")
        #thinc.api.use_pytorch_for_gpu_memory()
    C = load_config(path)
    model = C["model"]
    optimizer = C["optimizer"]
    calculate_loss = sequence_categorical_crossentropy
    cfg = C["training"]

    (train_X, train_Y), (dev_X, dev_Y) = ml_datasets.ud_ancora_pos_tags()
    # Convert the outputs to cupy (if we're using that)
    print(type(dev_Y[0]))
    train_Y = list(map(model.ops.asarray, train_Y))
    dev_Y = list(map(model.ops.asarray, dev_Y))
    # Pass in a small batch of data, to fill in missing shapes.
    model.initialize(X=train_X[:5], Y=train_Y[:5])
    train_data: List[Tuple[Array2d, Array2d]]
    dev_data: List[Tuple[Array2d, Array2d]]
    train_data = list(zip(train_X, train_Y))
    train_data = list(zip(dev_X, dev_Y))

    d_guesses: List[Array2d]
    loss: float
    for epoch in range(cfg["n_epoch"]):
        random.shuffle(train_data)
        batch_count = 0
        train_data = tqdm.tqdm(train_data, leave=False)
        for batch in thinc.api.minibatch(train_data, cfg["batch_size"]):
            inputs, truths = zip(*batch)
            guesses, backprop = model(inputs, is_train=True)
            d_guesses = calculate_loss(guesses, truths)
            backprop(d_guesses)
            batch_count += 1
            if batch_count == 4:
                model.finish_update(optimizer)
                optimizer.step_schedules()
                batch_count = 0
        score = evaluate_sequences(model, dev_X, dev_Y, 128)
        print(epoch, score)


if __name__ == "__main__":
    main()
