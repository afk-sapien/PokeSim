FROM golang:1.27.1-alpine AS build
ENV CGO_ENABLED=0 GOTOOLCHAIN=local
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY main.go ./
RUN go build -mod=readonly -trimpath -o /caddy .
RUN go list -deps . > /packages.txt
RUN <<'SHELL'
set -eu
mkdir /notices
find /go/pkg/mod -type f \( -iname 'LICENSE*' -o -iname 'NOTICE*' -o -iname 'COPYING*' \) | while IFS= read -r license_file
do
    relative=${license_file#/go/pkg/mod/}
    mkdir -p "/notices/$(dirname "$relative")"
    cp "$license_file" "/notices/$relative"
done
SHELL

FROM caddy:2.11.4-alpine
RUN apk upgrade --no-cache
COPY --from=build /caddy /usr/bin/caddy
COPY --from=build /notices /usr/share/pokesim-proxy/licenses
COPY --from=build /packages.txt /usr/share/pokesim-proxy/packages.txt
COPY go.mod go.sum main.go /usr/share/pokesim-proxy/
