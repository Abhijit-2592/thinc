from typing import Optional, Tuple, Array
from .. import Model
from ..util import get_width


def Siamese(layer, similarity):
    return Model(
        f"siamese({layer.name}, {similarity.name})",
        forward,
        init=init,
        layers=[layer, similarity],
        dims={"nI": layer.get_dim("nI"), "nO": similarity.get_dim("nO")},
    )


def init(model, X: Optional[Tuple[Array, Array]] = None, Y: Optional[Array] = None):
    if X is not None:
        X1, X2 = X
        model.layers[0].set_dim("nI", get_width(X1))
    else:
        X1 = None
        X2 = None
    if Y is not None:
        model.layers[1].set_dim("nO", get_width(Y))
    model.layers[0].initialize(X=X1)
    out1 = model.layers[0].predict(X1)
    out2 = model.layers[0].predict(X2)
    model.layers[1].initialize(X=(out1, out2), Y=Y)
    model.set_dim("nI", model.layers[0].get_dim("nI"))
    model.set_dim("nO", model.layers[1].get_dim("nO"))


def forward(model, X1_X2, is_train):
    X1, X2 = X1_X2
    vec1, bp_vec1 = model.layers[0](X1, is_train)
    vec2, bp_vec2 = model.layers[0](X2, is_train)
    output, bp_output = model.layers[1]((vec1, vec2), is_train)

    def finish_update(d_output):
        d_vec1, d_vec2 = bp_output(d_output)
        d_input1 = bp_vec1(d_vec1)
        d_input2 = bp_vec2(d_vec2)
        return (d_input1, d_input2)

    return output, finish_update
