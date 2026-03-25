package device

import (
	"github.com/google/wire"
)

// ProviderSet exposes LED providers for Wire.
// ProvideDriver returns (*Driver, error); injector will have (*Server, error) if used at top level.
var ProviderSet = wire.NewSet(
	ProvideService,
)
