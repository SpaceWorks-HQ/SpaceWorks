def wp3_dataset_specs(predicate):
    return {'notifications.MemberBroadcast': ('notifications/broadcasts.csv', predicate(('makerspace',)))}
