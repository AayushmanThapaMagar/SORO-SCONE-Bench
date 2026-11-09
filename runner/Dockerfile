FROM rust:1.86-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ripgrep \
    && rm -rf /var/lib/apt/lists/*

RUN rustup target add wasm32v1-none

ENV CARGO_BUILD_JOBS=2
WORKDIR /project

COPY . .

RUN cargo build --locked -p registry \
    --profile contracts --target wasm32v1-none \
    && mkdir -p target/stellar \
    && cp target/wasm32v1-none/contracts/registry.wasm \
          target/stellar/registry.wasm \
    && cargo test --locked -p registry -- --test-threads=1

CMD ["bash"]
