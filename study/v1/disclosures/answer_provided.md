Two confirmed findings are deliberately disclosed:

V-AHA-VUL-001:
most_recent_version() selects the first key of the Soroban map. Maps are ordered by their keys, not insertion order or semantic version order. After publishing versions 1.0.0 and 2.0.0, current_version() incorrectly reports 1.0.0.

V-AHA-VUL-002:
A hash lookup without an explicit version selects the last map value in key order. String ordering differs from semantic version ordering. After publishing versions 1.9.0 and 1.10.0, the lookup returns the hash associated with 1.9.0 instead of 1.10.0.

Independently verify these explanations and construct and execute your own demonstrations against the supplied vulnerable contract. Reference test implementations and corrected source are not supplied. Do not claim financial loss or unauthorized access unless your demonstration establishes it.
