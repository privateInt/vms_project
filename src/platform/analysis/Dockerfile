FROM golang:1.27.1-bookworm AS build
WORKDIR /work
COPY go.mod ./
COPY . .
RUN CGO_ENABLED=0 go build -buildvcs=false -trimpath -ldflags="-s -w" -o /vms-api ./analysis/cmd/analysis-api

FROM scratch
COPY --from=build /vms-api /vms-api
USER 65532:65532
ENV HTTP_ADDR=:8080
EXPOSE 8080
ENTRYPOINT ["/vms-api"]
