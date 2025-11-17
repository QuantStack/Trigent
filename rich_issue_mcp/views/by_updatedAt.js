function(doc) {
    if (doc.updatedAt) {
        emit(doc.updatedAt, null);
    }
}