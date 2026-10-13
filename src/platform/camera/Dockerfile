FROM golang:1.27.1-bookworm AS build
WORKDIR /work
COPY go.mod go.sum ./
COPY . .
RUN CGO_ENABLED=0 go build -buildvcs=false -trimpath -ldflags="-s -w" -o /vms-api ./camera/cmd/camera-api
RUN CGO_ENABLED=0 go build -buildvcs=false -trimpath -ldflags="-s -w" -o /camera-migrate ./camera/cmd/camera-migrate

FROM scratch
COPY --from=build /vms-api /vms-api
COPY --from=build /camera-migrate /camera-migrate
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
USER 65532:65532
ENV HTTP_ADDR=:8080
EXPOSE 8080
ENTRYPOINT ["/vms-api"]
