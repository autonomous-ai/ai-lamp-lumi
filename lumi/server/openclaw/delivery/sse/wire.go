package sse

import (
	"github.com/google/wire"
)

var ProviderSet = wire.NewSet(
	ProvideOpenClawHandler,
)
