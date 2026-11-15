# Third-party notices

## CREAK

This project uses portions of **CREAK: A Dataset for Commonsense Reasoning over Entity Knowledge**, by Yasumasa Onoe, Michael J.Q. Zhang, Eunsol Choi, and Greg Durrett (NeurIPS 2021 Datasets and Benchmarks Track).

- Source repository: <https://github.com/yasumasaonoe/creak>
- Paper: <https://arxiv.org/abs/2109.01653>
- Upstream revision checked: `5e892b28b6dad3e87769cfc01f00a6577ca44068`
- Upstream license: [MIT, LICENSE.txt](https://github.com/yasumasaonoe/creak/blob/5e892b28b6dad3e87769cfc01f00a6577ca44068/LICENSE.txt)
- Unmodified local copy of the upstream notice and license: [third_party/CREAK-LICENSE.txt](third_party/CREAK-LICENSE.txt)

Copyright (c) 2021 Yasumasa Onoe, Michael J.Q. Zhang, Eunsol Choi, and Greg Durrett

The upstream MIT copyright and permission notice must be preserved with copies or substantial portions of the CREAK material. The project's own [LICENSE](LICENSE) does not replace the upstream authors' notice.

### Material included in this repository

CREAK-derived material includes:

- The candidate pool and curated claims under `dataset/selected_data/`, including CREAK sentences, IDs, labels, and their provenance metadata.
- CREAK sentences reproduced in `dataset/selected_data/curated_claims_bundle/curation_review.json` alongside project-specific review notes.
- The example claims in `experiments/moral_memory/claims.jsonl` and CREAK-derived prompt examples in `inputs/request.json`, `inputs/requests.jsonl`, and documentation.

This project converts CREAK fields into versioned `Claim` records, selects subsets, and adds experimental metadata and editorial review notes. These subsets and reviews are project artifacts, not an official CREAK release or endorsement. The curated subset's seed records the original candidate-pool sampling, not a random selection of the final curated subset; see the accompanying curation review for its selection procedure and limitations.

Raw CREAK files are not bundled. They can be obtained from the upstream repository as described in [dataset/README.md](dataset/README.md). The local `dataset/creak` directory or symlink is ignored by Git.

### Citation

The upstream repository provides the following citation:

```bibtex
@article{onoe2021creak,
  title={CREAK: A Dataset for Commonsense Reasoning over Entity Knowledge},
  author={Onoe, Yasumasa and Zhang, Michael J.Q. and Choi, Eunsol and Durrett, Greg},
  journal={OpenReview},
  year={2021}
}
```

Third-party dependencies installed through Python packaging retain their own licenses. They are not vendored into this source repository.
