from copy import deepcopy
from functools import reduce
from collections import Counter
from typing import Union, Optional

import numpy as np
import pandas as pd
import matplotlib.pylab as plt
import altair as alt
from sklearn.utils import deprecated
from sklearn.preprocessing import normalize
from sklearn.metrics import pairwise_distances
from sklearn.metrics.pairwise import (
    paired_distances,
    cosine_similarity,
    cosine_distances,
    euclidean_distances,
)

from whatlies.embedding import Embedding
from whatlies.common import plot_graph_layout, handle_2d_plot


class EmbeddingSet:
    """
    This object represents a set of `Embedding`s. You can use the same operations
    as an `Embedding` but here we apply it to the entire set instead of a single
    `Embedding`.

    **Parameters**

    - **embeddings**: list of `Embedding`, or a single dictionary containing name:`Embedding` pairs
    - **name**: custom name of embeddingset

    Usage:

    ```python
    from whatlies.embedding import Embedding
    from whatlies.embeddingset import EmbeddingSet

    foo = Embedding("foo", [0.1, 0.3])
    bar = Embedding("bar", [0.7, 0.2])
    emb = EmbeddingSet(foo, bar)
    emb = EmbeddingSet({'foo': foo, 'bar': bar)
    ```
    """

    def __init__(self, *embeddings, name=None):
        if not name:
            name = "EmbSet"
        self.name = name
        if isinstance(embeddings[0], dict):
            # Assume it's a single dictionary.
            self.embeddings = embeddings[0]
        else:
            # Assume it's a list of `Embedding` instances.
            names = [t.name for t in embeddings]
            if len(names) != len(set(names)):
                double_names = [k for k, v in Counter(names).items() if v > 1]
                raise Warning(
                    f"Some embeddings given to `EmbeddingSet` have the same name: {double_names}."
                )
            self.embeddings = {t.name: t for t in embeddings}

        # We cannot allow for different shapes because that will break many operations later.
        uniq_shapes = set(v.vector.shape for k, v in self.embeddings.items())
        if len(uniq_shapes) > 1:
            raise ValueError("Not all vectors have the same shape.")

    @property
    def ndim(self):
        """
        Return dimension of embedding vectors in embeddingset.
        """
        return next(iter(self.embeddings.values())).ndim

    def __contains__(self, item):
        """
        Checks if an item is in the embeddingset.

        Usage:

        ```python
        from whatlies.embedding import Embedding
        from whatlies.embeddingset import EmbeddingSet

        foo = Embedding("foo", [0.1, 0.3])
        bar = Embedding("bar", [0.7, 0.2])
        buz = Embedding("buz", [0.1, 0.9])
        emb = EmbeddingSet(foo, bar)

        "foo" in emb # True
        "dinosaur" in emb # False
        ```
        """
        return item in self.embeddings.keys()

    def __getitem__(self, thing):
        """
        Retreive a single embedding from the embeddingset.

        Usage:
        ```python
        from whatlies.embeddingset import EmbeddingSet

        foo = Embedding("foo", [0.1, 0.3, 0.10])
        bar = Embedding("bar", [0.7, 0.2, 0.11])
        buz = Embedding("buz", [0.1, 0.9, 0.12])
        emb = EmbeddingSet(foo, bar, buz)

        emb["buz"]
        ```
        """
        if isinstance(thing, str):
            return self.embeddings[thing]
        new_embeddings = {t: self[t] for t in thing}
        names = ",".join(thing)
        return EmbeddingSet(new_embeddings, name=f"{self.name}.subset({names})")

    def __iter__(self):
        """
        Iterate over all the embeddings in the embeddingset.

        Usage:

        ```python
        from whatlies.embedding import Embedding
        from whatlies.embeddingset import EmbeddingSet

        foo = Embedding("foo", [0.1, 0.3])
        bar = Embedding("bar", [0.7, 0.2])
        buz = Embedding("buz", [0.1, 0.9])
        emb = EmbeddingSet(foo, bar)

        [e for e in emb]
        ```
        """
        return self.embeddings.values().__iter__()

    def __add__(self, other):
        """
        Adds an embedding to each element in the embeddingset.

        Usage:

        ```python
        from whatlies.embedding import Embedding
        from whatlies.embeddingset import EmbeddingSet

        foo = Embedding("foo", [0.1, 0.3])
        bar = Embedding("bar", [0.7, 0.2])
        buz = Embedding("buz", [0.1, 0.9])
        emb = EmbeddingSet(foo, bar)

        (emb).plot(kind="arrow")
        (emb + buz).plot(kind="arrow")
        ```
        """
        new_embeddings = {k: emb + other for k, emb in self.embeddings.items()}
        return EmbeddingSet(new_embeddings, name=f"({self.name} + {other.name})")

    def __sub__(self, other):
        """
        Subtracts an embedding from each element in the embeddingset.

        Usage:

        ```python
        from whatlies.embedding import Embedding
        from whatlies.embeddingset import EmbeddingSet

        foo = Embedding("foo", [0.1, 0.3])
        bar = Embedding("bar", [0.7, 0.2])
        buz = Embedding("buz", [0.1, 0.9])
        emb = EmbeddingSet(foo, bar)

        (emb).plot(kind="arrow")
        (emb - buz).plot(kind="arrow")
        ```
        """
        new_embeddings = {k: emb - other for k, emb in self.embeddings.items()}
        return EmbeddingSet(new_embeddings, name=f"({self.name} - {other.name})")

    def __or__(self, other: Union["Embedding", "EmbeddingSet"]) -> "EmbeddingSet":
        """
        Makes every element in the embeddingset othogonal to the passed embedding.

        Usage:

        ```python
        from whatlies.embedding import Embedding
        from whatlies.embeddingset import EmbeddingSet

        foo = Embedding("foo", [0.1, 0.3])
        bar = Embedding("bar", [0.7, 0.2])
        buz = Embedding("buz", [0.1, 0.9])
        emb = EmbeddingSet(foo, bar)

        (emb).plot(kind="arrow")
        (emb | buz).plot(kind="arrow")
        ```
        """
        if isinstance(other, Embedding):
            new_embeddings = {k: emb | other for k, emb in self.embeddings.items()}
        elif isinstance(other, EmbeddingSet):
            # Apply Gram-Schmidt to project away from a hyperplane instead of an axis
            # First, create orthogonal vectors that span the space to project away from
            orth_away = [w for w in other]
            for i in range(len(orth_away)):
                orth_away[i] = reduce(lambda a, b: b | a, orth_away[: i + 1])

            # Next, use all of these vectors to project away from
            new_set = EmbeddingSet(self.embeddings.copy())
            for e in orth_away:
                new_set = new_set | e
            return new_set
        else:
            raise ValueError(
                f"You must project away from either an Embedding or an Embeddingset. Got={type(other)}"
            )
        return EmbeddingSet(new_embeddings, name=f"({self.name} | {other.name})")

    def __rshift__(self, other):
        """
        Maps every embedding in the embedding set unto the passed embedding.

        Usage:

        ```python
        from whatlies.embedding import Embedding
        from whatlies.embeddingset import EmbeddingSet

        foo = Embedding("foo", [0.1, 0.3])
        bar = Embedding("bar", [0.7, 0.2])
        buz = Embedding("buz", [0.1, 0.9])
        emb = EmbeddingSet(foo, bar)

        (emb).plot(kind="arrow")
        (emb >> buz).plot(kind="arrow")
        ```
        """
        new_embeddings = {k: emb >> other for k, emb in self.embeddings.items()}
        return EmbeddingSet(new_embeddings, name=f"({self.name} >> {other.name})")

    def compare_against(self, other, mapping="direct"):
        if mapping == "direct":
            return [v > other for k, v in self.embeddings.items()]

    def pipe(self, func, *args, **kwargs):
        """
        Applies a function to the embedding set. Useful for method chaining and
        chunks of code that repeat.

        Arguments:
             func: callable that accepts an `EmbeddingSet` set as its first argument
             args: arguments to also pass to the function
             kwargs: keyword arguments to also pass to the function

        ```python
        from whatlies.language import SpacyLanguage, BytePairLanguage

        lang_sp = SpacyLanguage("en_core_web_sm")
        lang_bp = BytePairLanguage("en", dim=25, vs=1000)

        text = ["cat", "dog", "rat", "blue", "red", "yellow"]

        def make_plot(embset):
            return (embset
                    .plot_interactive("dog", "blue")
                    .properties(height=200, width=200))

        p1 = lang_sp[text].pipe(make_plot)
        p2 = lang_bp[text].pipe(make_plot)
        p1 | p2
        ```
        """
        return func(self, *args, **kwargs)

    def to_X(self, norm=False):
        """
        Takes every vector in each embedding and turns it into a scikit-learn compatible `X` matrix.

        Usage:

        ```python
        from whatlies.embedding import Embedding
        from whatlies.embeddingset import EmbeddingSet

        foo = Embedding("foo", [0.1, 0.3])
        bar = Embedding("bar", [0.7, 0.2])
        buz = Embedding("buz", [0.1, 0.9])
        emb = EmbeddingSet(foo, bar, buz)

        X = emb.to_X()
        ```
        """
        X = np.array([i.vector for i in self.embeddings.values()])
        X = normalize(X) if norm else X
        return X

    def to_X_y(self, y_label):
        """
        Takes every vector in each embedding and turns it into a scikit-learn compatible `X` matrix.
        Also retreives an array with potential labels.

        Usage:

        ```python
        from whatlies.embedding import Embedding
        from whatlies.embeddingset import EmbeddingSet

        foo = Embedding("foo", [0.1, 0.3])
        bar = Embedding("bar", [0.7, 0.2])
        buz = Embedding("buz", [0.1, 0.9])
        bla = Embedding("bla", [0.2, 0.8])

        emb1 = EmbeddingSet(foo, bar).add_property("label", lambda d: 'group-one')
        emb2 = EmbeddingSet(buz, bla).add_property("label", lambda d: 'group-two')
        emb = emb1.merge(emb2)

        X, y = emb.to_X_y(y_label='label')
        ```
        """
        X = self.to_X()
        y = np.array([getattr(e, y_label) for e in self.embeddings.values()])
        return X, y

    def to_names_X(self):
        """
        Get the list of names as well as an array of vectors of all embeddings.

        Usage:

        ```python
        from whatlies.embedding import Embedding
        from whatlies.embeddingset import EmbeddingSet

        foo = Embedding("foo", [0.1, 0.3])
        bar = Embedding("bar", [0.7, 0.2])
        buz = Embedding("buz", [0.1, 0.9])
        emb = EmbeddingSet(foo, bar, buz)

        names, X = emb.to_names_X()
        """
        return list(self.embeddings.keys()), self.to_X()

    @classmethod
    def from_names_X(cls, names, X):
        """
        Constructs an `EmbeddingSet` instance from the given embedding names and vectors.

        Arguments:
            names: an iterable containing the names of embeddings
            X: an iterable of 1D vectors, or a 2D numpy array; it should have the same length as `names`

        Usage:

        ```python
        from whatlies.embeddingset import EmbeddingSet

        names = ["foo", "bar", "buz"]
        vecs = [
            [0.1, 0.3],
            [0.7, 0.2],
            [0.1, 0.9],
        ]

        emb = EmbeddingSet.from_names_X(names, vecs)
        """
        X = np.array(X)
        if len(X) != len(names):
            raise ValueError(
                f"The number of given names ({len(names)}) and vectors ({len(X)}) should be the same."
            )
        return cls({n: Embedding(n, v) for n, v in zip(names, X)})

    def transform(self, transformer):
        """
        Applies a transformation on the entire set.

        Usage:

        ```python
        from whatlies.embeddingset import EmbeddingSet
        from whatlies.transformers import Pca

        foo = Embedding("foo", [0.1, 0.3, 0.10])
        bar = Embedding("bar", [0.7, 0.2, 0.11])
        buz = Embedding("buz", [0.1, 0.9, 0.12])
        emb = EmbeddingSet(foo, bar, buz).transform(Pca(2))
        ```
        """
        return transformer(self)

    def __repr__(self):
        return self.name

    def __str__(self):
        return self.name

    def __len__(self):
        return len(self.embeddings.keys())

    def filter(self, func):
        """
        Filters the collection of embeddings based on a predicate function.

        Arguments:
             func: callable that accepts a single embedding and outputs a boolean

        ```python
        from whatlies.embeddingset import EmbeddingSet

        foo = Embedding("foo", [0.1, 0.3, 0.10])
        bar = Embedding("bar", [0.7, 0.2, 0.11])
        buz = Embedding("buz", [0.1, 0.9, 0.12])
        xyz = Embedding("xyz", [0.1, 0.9, 0.12])
        emb = EmbeddingSet(foo, bar, buz, xyz)
        emb.filter(lambda e: "foo" not in e.name)
        ```
        """
        return EmbeddingSet({k: v for k, v in self.embeddings.items() if func(v)})

    def merge(self, other):
        """
        Concatenates two embeddingssets together

        Arguments:
            other: another embeddingset

        Usage:

        ```python
        from whatlies.embeddingset import EmbeddingSet

        foo = Embedding("foo", [0.1, 0.3, 0.10])
        bar = Embedding("bar", [0.7, 0.2, 0.11])
        buz = Embedding("buz", [0.1, 0.9, 0.12])
        xyz = Embedding("xyz", [0.1, 0.9, 0.12])
        emb1 = EmbeddingSet(foo, bar)
        emb2 = EmbeddingSet(xyz, buz)

        both = emb1.merge(emb2)
        ```
        """
        return EmbeddingSet({**self.embeddings, **other.embeddings})

    def add_property(self, name, func):
        """
        Adds a property to every embedding in the set. Very useful for plotting because
        a property can be used to assign colors.

        Arguments:
            name: name of the property to add
            func: function that receives an embedding and needs to output the property value

        Usage:

        ```python
        from whatlies.embeddingset import EmbeddingSet

        foo = Embedding("foo", [0.1, 0.3, 0.10])
        bar = Embedding("bar", [0.7, 0.2, 0.11])
        emb = EmbeddingSet(foo, bar)
        emb_with_property = emb.add_property('example', lambda d: 'group-one')
        ```
        """
        return EmbeddingSet(
            {k: e.add_property(name, func) for k, e in self.embeddings.items()}
        )

    def average(self, name=None):
        """
        Takes the average over all the embedding vectors in the embeddingset. Turns it into
        a new `Embedding`.

        Arguments:
            name: manually specify the name of the average embedding

        Usage:

        ```python
        from whatlies.embeddingset import EmbeddingSet

        foo = Embedding("foo", [1.0, 0.0])
        bar = Embedding("bar", [0.0, 1.0])
        emb = EmbeddingSet(foo, bar)

        emb.average().vector                   # [0.5, 0,5]
        emb.average(name="the-average").vector # [0.5, 0.5]
        ```
        """
        name = f"{self.name}.average()" if not name else name
        x = self.to_X()
        return Embedding(name, np.mean(x, axis=0))

    def embset_similar(self, emb: Union[str, Embedding], n: int = 10, metric="cosine"):
        """
        Retreive an [EmbeddingSet][whatlies.embeddingset.EmbeddingSet] that are the most simmilar to the passed query.

        Arguments:
            emb: query to use
            n: the number of items you'd like to see returned
            metric: metric to use to calculate distance, must be scipy or sklearn compatible

        Returns:
            An [EmbeddingSet][whatlies.embeddingset.EmbeddingSet] containing the similar embeddings.
        """
        embs = [w[0] for w in self.score_similar(emb, n, metric)]
        return EmbeddingSet({w.name: w for w in embs})

    def score_similar(self, emb: Union[str, Embedding], n: int = 10, metric="cosine"):
        """
        Retreive a list of (Embedding, score) tuples that are the most similar to the passed query.

        Arguments:
            emb: query to use
            n: the number of items you'd like to see returned
            metric: metric to use to calculate distance, must be scipy or sklearn compatible

        Returns:
            An list of ([Embedding][whatlies.embedding.Embedding], score) tuples.
        """
        if n > len(self):
            raise ValueError(
                f"You cannot retreive (n={n}) more items than exist in the Embeddingset (len={len(self)})"
            )

        if isinstance(emb, str):
            if emb not in self.embeddings.keys():
                raise ValueError(
                    f"Embedding for `{emb}` does not exist in this EmbeddingSet"
                )
            emb = self[emb]

        vec = emb.vector
        queries = [w for w in self.embeddings.keys()]
        vector_matrix = self.to_X()
        distances = pairwise_distances(vector_matrix, vec.reshape(1, -1), metric=metric)
        by_similarity = sorted(zip(queries, distances), key=lambda z: z[1])
        return [(self[q], float(d)) for q, d in by_similarity[:n]]

    def to_matrix(self):
        """
        Does exactly the same as `.to_X`. It takes the embedding vectors and turns it into a numpy array.
        """
        return self.to_X()

    def to_dataframe(self):
        """
        Turns the embeddingset into a pandas dataframe.
        """
        mat = self.to_matrix()
        return pd.DataFrame(mat, index=list(self.embeddings.keys()))

    def movement_df(self, other, metric="euclidean"):
        """
        Creates a dataframe that shows the movement from one embeddingset to another one.

        Arguments:
            other: the other embeddingset to compare against, will only keep the overlap
            metric: metric to use to calculate movement, must be scipy or sklearn compatible

        Usage:

        ```python
        from whatlies.language import SpacyLanguage

        lang = SpacyLanguage("en_core_web_sm")

        names = ['red', 'blue', 'green', 'yellow', 'cat', 'dog', 'mouse', 'rat', 'bike', 'car']
        emb = lang[names]
        emb_ort = lang[names] | lang['cat']
        emb.movement_df(emb_ort)
        ```
        """
        overlap = list(
            set(self.embeddings.keys()).intersection(set(other.embeddings.keys()))
        )
        mat1 = np.array([w.vector for w in self[overlap]])
        mat2 = np.array([w.vector for w in other[overlap]])
        return (
            pd.DataFrame(
                {"name": overlap, "movement": paired_distances(mat1, mat2, metric)}
            )
            .sort_values(["movement"], ascending=False)
            .reset_index()
        )

    def to_axis_df(self, x_axis, y_axis):
        if isinstance(x_axis, str):
            x_axis = self[x_axis]
        if isinstance(y_axis, str):
            y_axis = self[y_axis]
        return pd.DataFrame(
            {
                "x_axis": self.compare_against(x_axis),
                "y_axis": self.compare_against(y_axis),
                "name": [v.name for v in self.embeddings.values()],
                "original": [v.orig for v in self.embeddings.values()],
            }
        )

    def plot(
        self,
        kind: str = "arrow",
        x_axis: Union[int, str, Embedding] = 0,
        y_axis: Union[int, str, Embedding] = 1,
        x_label: Optional[str] = None,
        y_label: Optional[str] = None,
        title: Optional[str] = None,
        color: str = None,
        show_ops: bool = False,
        annot: bool = True,
        axis_option: Optional[str] = None,
    ):
        """
        Makes (perhaps inferior) matplotlib plot. Consider using `plot_interactive` instead.

        Arguments:
            kind: what kind of plot to make, can be `scatter`, `arrow` or `text`
            x_axis: the x-axis to be used, must be given when dim > 2; if an integer, the corresponding
                dimension of embedding is used.
            y_axis: the y-axis to be used, must be given when dim > 2; if an integer, the corresponding
                dimension of embedding is used.
            x_label: an optional label used for x-axis; if not given, it is set based on value of `x_axis`.
            y_label: an optional label used for y-axis; if not given, it is set based on value of `y_axis`.
            title: an optional title for the plot.
            color: the color of the dots
            show_ops: setting to also show the applied operations, only works for `text`
            annot: should the points be annotated
            axis_option: a string which is passed as `option` argument to `matplotlib.pyplot.axis` in order to control
                axis properties (e.g. using `'equal'` make circles shown circular in the plot). This might be useful
                for preserving geometric relationships (e.g. orthogonality) in the generated plot. See `matplotlib.pyplot.axis`
                [documentation](https://matplotlib.org/3.1.0/api/_as_gen/matplotlib.pyplot.axis.html#matplotlib-pyplot-axis)
                for possible values and their description.
        """
        if isinstance(x_axis, str):
            x_axis = self[x_axis]
        if isinstance(y_axis, str):
            y_axis = self[y_axis]
        embeddings = []
        for emb in self.embeddings.values():
            x_val, x_lab = emb._get_plot_axis_value_and_label(x_axis, dir="x")
            y_val, y_lab = emb._get_plot_axis_value_and_label(y_axis, dir="y")
            emb_plot = Embedding(name=emb.name, vector=[x_val, y_val], orig=emb.orig)
            embeddings.append(emb_plot)
        x_label = x_lab if x_label is None else x_label
        y_label = y_lab if y_label is None else y_label
        handle_2d_plot(
            embeddings,
            kind=kind,
            color=color,
            xlabel=x_label,
            ylabel=y_label,
            title=title,
            show_operations=show_ops,
            annot=annot,
            axis_option=axis_option,
        )
        return self

    def plot_graph_layout(self, kind="cosine", **kwargs):
        plot_graph_layout(self.embeddings, kind, **kwargs)
        return self

    @deprecated(
        "This method will be deprecated in v0.6.0 in favor of `plot_distance` and `plot_similarity`"
    )
    def plot_correlation(self, metric=None):
        """
        Make a correlation plot. Shows you the correlation between all the word embeddings. Can
        also be configured to show distances instead.

        Arguments:
            metric: don't plot correlation but a distance measure, must be scipy compatible (cosine, euclidean, etc)

        Warning:
            This method will be deprecated in version 0.6.0 in favor of `plot_distance` and `plot_similarity`.

        Usage:

        ```python
        from whatlies.language import SpacyLanguage
        import matplotlib.pyplot as plt

        lang = SpacyLanguage("en_core_web_sm")

        names = ['red', 'blue', 'green', 'yellow', 'cat', 'dog', 'mouse', 'rat', 'bike', 'car']
        emb = lang[names]
        emb.plot_correlation()
        ```
        """
        df = self.to_dataframe().T
        corr_df = (
            pairwise_distances(self.to_matrix(), metric=metric) if metric else df.corr()
        )

        fig, ax = plt.subplots()
        plt.imshow(corr_df)
        plt.xticks(range(len(df.columns)), df.columns)
        plt.yticks(range(len(df.columns)), df.columns)
        plt.colorbar()

        # Rotate the tick labels and set their alignment.
        plt.setp(ax.get_xticklabels(), rotation=90, ha="right", rotation_mode="anchor")

    def plot_similarity(self, metric="cosine", norm=False):
        """
        Make a similarity plot. Shows you the similarity between all the word embeddings in the set.

        Arguments:
            metric: `'cosine'` or `'correlation'`
            norm: normalise the embeddings before calculating the similarity

        Usage:

        ```python
        from whatlies.language import SpacyLanguage
        lang = SpacyLanguage("en_core_web_sm")

        names = ['red', 'blue', 'green', 'yellow', 'cat', 'dog', 'mouse', 'rat', 'bike', 'car']
        emb = lang[names]
        emb.plot_similarity()
        emb.plot_similarity(metric='correlation')
        ```
        """
        allowed_metrics = ["cosine", "correlation"]
        if metric not in allowed_metrics:
            raise ValueError(
                f"The `metric` argument must be in {allowed_metrics}, got: {metric}."
            )

        vmin, vmax = 0, 1
        X = self.to_X(norm=norm)
        if metric == "cosine":
            similarity = cosine_similarity(X)
        if metric == "correlation":
            similarity = np.corrcoef(X)
            vmin, vmax = -1, 1

        fig, ax = plt.subplots()
        plt.imshow(similarity, cmap=plt.cm.get_cmap(), vmin=-vmin, vmax=vmax)
        plt.xticks(range(len(self)), self.embeddings.keys())
        plt.yticks(range(len(self)), self.embeddings.keys())
        plt.colorbar()

        # Rotate the tick labels and set their alignment.
        plt.setp(ax.get_xticklabels(), rotation=90, ha="right", rotation_mode="anchor")

    def plot_distance(self, metric="cosine", norm=False):
        """
        Make a distance plot. Shows you the distance between all the word embeddings in the set.

        Arguments:
            metric: `'cosine'`, `'correlation'` or `'euclidean'`
            norm: normalise the vectors before calculating the distances

        Usage:

        ```python
        from whatlies.language import SpacyLanguage
        lang = SpacyLanguage("en_core_web_sm")

        names = ['red', 'blue', 'green', 'yellow', 'cat', 'dog', 'mouse', 'rat', 'bike', 'car']
        emb = lang[names]
        emb.plot_distance(metric='cosine')
        emb.plot_distance(metric='euclidean')
        emb.plot_distance(metric='correlation')
        ```
        """
        allowed_metrics = ["cosine", "correlation", "euclidean"]
        if metric not in allowed_metrics:
            raise ValueError(
                f"The `metric` argument must be in {allowed_metrics}, got: {metric}."
            )

        vmin, vmax = 0, 1
        X = self.to_X(norm=norm)
        if metric == "cosine":
            distances = cosine_distances(X)
        if metric == "correlation":
            distances = 1 - np.corrcoef(X)
            vmin, vmax = -1, 1
        if metric == "euclidean":
            distances = euclidean_distances(X)
            vmin, vmax = 0, np.max(distances)

        fig, ax = plt.subplots()
        plt.imshow(distances, cmap=plt.cm.get_cmap().reversed(), vmin=vmin, vmax=vmax)
        plt.xticks(range(len(self)), self.embeddings.keys())
        plt.yticks(range(len(self)), self.embeddings.keys())
        plt.colorbar()

        # Rotate the tick labels and set their alignment.
        plt.setp(ax.get_xticklabels(), rotation=90, ha="right", rotation_mode="anchor")

    def plot_pixels(self):
        """
        Makes a pixelchart of every embedding in the set.

        Usage:

        ```python
        from whatlies.language import SpacyLanguage
        from whatlies.transformers import Pca

        lang = SpacyLanguage("en_core_web_sm")

        names = ['red', 'blue', 'green', 'yellow',
                 'cat', 'dog', 'mouse', 'rat',
                 'bike', 'car', 'motor', 'cycle',
                 'firehydrant', 'japan', 'germany', 'belgium']
        emb = lang[names].transform(Pca(12)).filter(lambda e: 'pca' not in e.name)
        emb.plot_pixels()
        ```

        ![](https://rasahq.github.io/whatlies/images/pixels.png)
        """
        names = self.embeddings.keys()
        df = self.to_dataframe()
        plt.matshow(df)
        plt.yticks(range(len(names)), names)

    def plot_movement(
        self,
        other,
        x_axis: Union[str, Embedding],
        y_axis: Union[str, Embedding],
        first_group_name="before",
        second_group_name="after",
        annot: bool = True,
    ):
        """
        Makes highly interactive plot of the movement of embeddings
        between two sets of embeddings.

        Arguments:
            other: the other embeddingset
            x_axis: the x-axis to be used, must be given when dim > 2
            y_axis: the y-axis to be used, must be given when dim > 2
            first_group_name: the name to give to the first set of embeddings (default: "before")
            second_group_name: the name to give to the second set of embeddings (default: "after")
            annot: drawn points should be annotated

        **Usage**

        ```python
        from whatlies.language import SpacyLanguage

        words = ["prince", "princess", "nurse", "doctor", "banker", "man", "woman",
                 "cousin", "neice", "king", "queen", "dude", "guy", "gal", "fire",
                 "dog", "cat", "mouse", "red", "bluee", "green", "yellow", "water",
                 "person", "family", "brother", "sister"]

        lang = SpacyLanguage("en_core_web_sm")
        emb = lang[words]
        emb_new = emb - emb['king']

        emb.plot_movement(emb_new, 'man', 'woman')
        ```
        """
        if isinstance(x_axis, str):
            x_axis = self[x_axis]
        if isinstance(y_axis, str):
            y_axis = self[y_axis]

        df1 = (
            self.to_axis_df(x_axis, y_axis).set_index("original").drop(columns=["name"])
        )
        df2 = (
            other.to_axis_df(x_axis, y_axis)
            .set_index("original")
            .drop(columns=["name"])
            .loc[lambda d: d.index.isin(df1.index)]
        )
        df_draw = (
            pd.concat([df1, df2])
            .reset_index()
            .sort_values(["original"])
            .assign(constant=1)
        )

        plots = []
        for idx, grp_df in df_draw.groupby("original"):
            _ = (
                alt.Chart(grp_df)
                .mark_line(color="gray", strokeDash=[2, 1])
                .encode(x="x_axis:Q", y="y_axis:Q")
            )
            plots.append(_)
        p0 = reduce(lambda x, y: x + y, plots)

        p1 = (
            deepcopy(self)
            .add_property("group", lambda d: first_group_name)
            .plot_interactive(
                x_axis, y_axis, annot=annot, show_axis_point=True, color="group"
            )
        )
        p2 = (
            deepcopy(other)
            .add_property("group", lambda d: second_group_name)
            .plot_interactive(
                x_axis, y_axis, annot=annot, show_axis_point=True, color="group"
            )
        )
        return p0 + p1 + p2

    def plot_interactive(
        self,
        x_axis: Union[int, str, Embedding] = 0,
        y_axis: Union[int, str, Embedding] = 1,
        x_label: Optional[str] = None,
        y_label: Optional[str] = None,
        title: Optional[str] = None,
        annot: bool = True,
        show_axis_point: bool = False,
        color: Union[None, str] = None,
    ):
        """
        Makes highly interactive plot of the set of embeddings.

        Arguments:
            x_axis: the x-axis to be used, must be given when dim > 2; if an integer, the corresponding
                dimension of embedding is used.
            y_axis: the y-axis to be used, must be given when dim > 2; if an integer, the corresponding
                dimension of embedding is used.
            x_label: an optional label used for x-axis; if not given, it is set based on `x_axis` value.
            y_label: an optional label used for y-axis; if not given, it is set based on `y_axis` value.
            title: an optional title for the plot; if not given, it is set based on `x_axis` and `y_axis` values.
            annot: drawn points should be annotated
            show_axis_point: ensure that the axis are drawn
            color: a property that will be used for plotting

        **Usage**

        ```python
        from whatlies.language import SpacyLanguage

        words = ["prince", "princess", "nurse", "doctor", "banker", "man", "woman",
                 "cousin", "neice", "king", "queen", "dude", "guy", "gal", "fire",
                 "dog", "cat", "mouse", "red", "bluee", "green", "yellow", "water",
                 "person", "family", "brother", "sister"]

        lang = SpacyLanguage("en_core_web_sm")
        emb = lang[words]

        emb.plot_interactive('man', 'woman')
        ```
        """
        if isinstance(x_axis, str):
            x_axis = self[x_axis]
        if isinstance(y_axis, str):
            y_axis = self[y_axis]

        # Determine axes values and labels
        if isinstance(x_axis, int):
            x_val = self.to_X()[:, x_axis]
            x_lab = "Dimension " + str(x_axis)
        else:
            x_val = self.compare_against(x_axis)
            x_lab = x_axis.name

        if isinstance(y_axis, int):
            y_val = self.to_X()[:, y_axis]
            y_lab = "Dimension " + str(y_axis)
        else:
            y_val = self.compare_against(y_axis)
            y_lab = y_axis.name
        x_label = x_label if x_label is not None else x_lab
        y_label = y_label if y_label is not None else y_lab
        title = title if title is not None else f"{x_lab} vs. {y_lab}"

        plot_df = pd.DataFrame(
            {
                "x_axis": x_val,
                "y_axis": y_val,
                "name": [v.name for v in self.embeddings.values()],
                "original": [v.orig for v in self.embeddings.values()],
            }
        )

        if color:
            plot_df[color] = [
                getattr(v, color) if hasattr(v, color) else ""
                for v in self.embeddings.values()
            ]

        if not show_axis_point:
            plot_df = plot_df.loc[lambda d: ~d["name"].isin([x_lab, y_lab])]

        result = (
            alt.Chart(plot_df)
            .mark_circle(size=60)
            .encode(
                x=alt.X("x_axis", axis=alt.Axis(title=x_label)),
                y=alt.X("y_axis", axis=alt.Axis(title=y_label)),
                tooltip=["name", "original"],
                color=alt.Color(":N", legend=None) if not color else alt.Color(color),
            )
            .properties(title=title)
            .interactive()
        )

        if annot:
            text = (
                alt.Chart(plot_df)
                .mark_text(dx=-15, dy=3, color="black")
                .encode(
                    x=alt.X("x_axis", axis=alt.Axis(title=x_label)),
                    y=alt.X("y_axis", axis=alt.Axis(title=y_label)),
                    text="original",
                )
            )
            result = result + text
        return result

    def plot_interactive_matrix(
        self,
        *axes: Union[int, str, Embedding],
        annot: bool = True,
        show_axis_point: bool = False,
        width: int = 200,
        height: int = 200,
    ):
        """
        Makes highly interactive plot of the set of embeddings.

        Arguments:
            axes: the axes that we wish to plot; each could be either an integer, the name of
                an existing embedding, or an `Embedding` instance (default: `0, 1`).
            annot: drawn points should be annotated
            show_axis_point: ensure that the axis are drawn
            width: width of the visual
            height: height of the visual

        **Usage**

        ```python
        from whatlies.language import SpacyLanguage
        from whatlies.transformers import Pca

        words = ["prince", "princess", "nurse", "doctor", "banker", "man", "woman",
                 "cousin", "neice", "king", "queen", "dude", "guy", "gal", "fire",
                 "dog", "cat", "mouse", "red", "bluee", "green", "yellow", "water",
                 "person", "family", "brother", "sister"]

        lang = SpacyLanguage("en_core_web_sm")
        emb = lang[words]

        emb.transform(Pca(3)).plot_interactive_matrix('pca_0', 'pca_1', 'pca_2')
        ```
        """
        # Set default value of axes, if not given.
        if len(axes) == 0:
            axes = [0, 1]

        # Get values of each axis according to their type.
        axes_vals = {}
        X = self.to_X()
        for axis in axes:
            if isinstance(axis, int):
                vals = X[:, axis]
                axes_vals["Dimension " + str(axis)] = vals
            else:
                if isinstance(axis, str):
                    axis = self[axis]
                vals = self.compare_against(axis)
                axes_vals[axis.name] = vals

        plot_df = pd.DataFrame(axes_vals)
        plot_df["name"] = [v.name for v in self.embeddings.values()]
        plot_df["original"] = [v.orig for v in self.embeddings.values()]
        axes_names = list(axes_vals.keys())

        if not show_axis_point:
            plot_df = plot_df.loc[lambda d: ~d["name"].isin(axes_names)]

        result = (
            alt.Chart(plot_df)
            .mark_circle()
            .encode(
                x=alt.X(alt.repeat("column"), type="quantitative"),
                y=alt.Y(alt.repeat("row"), type="quantitative"),
                tooltip=["name", "original"],
                text="original",
            )
        )
        if annot:
            text_stuff = result.mark_text(dx=-15, dy=3, color="black").encode(
                x=alt.X(alt.repeat("column"), type="quantitative"),
                y=alt.Y(alt.repeat("row"), type="quantitative"),
                tooltip=["name", "original"],
                text="original",
            )
            result = result + text_stuff

        result = (
            result.properties(width=width, height=height)
            .repeat(row=axes_names[::-1], column=axes_names)
            .interactive()
        )

        return result
