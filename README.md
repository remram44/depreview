# DepReview

A web-based platform to review your dependencies. It aims at helping developers check the status of the software packages they depend on.

Some information would be retrieved automatically, such as the list of versions for each package with their release dates. This allows us to give a warning:

* if new versions have been out and you are not yet using them
* if a software package hasn't put out an update in a while
* if the GitHub repository associated with the package is gone, or mark read-only

Some information can also be input manually, for example:

* if a maintainer put up a message about their package being deprecated
* if no version has come out but the developer is responsive (sometimes a package just doesn't need updating)
* if some metadata is missing from the package, for example the URL of its code repository or its license terms

This is very much a work in progress at the moment.
